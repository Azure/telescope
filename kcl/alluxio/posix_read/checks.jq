# Parsing and per-run validation of elbencho text results for the POSIX read benchmarks.

import "s3_read/checks" as s3;

# Seconds in an elbencho duration: "26.755s", "1m0.251s", "2h3m4.5s", or sub-second
# "850ms" / "120us" / "120µs". Anything else fails closed.
def elbencho_seconds:
  . as $text
  | if test("^(?:[0-9]+h)?(?:[0-9]+m)?[0-9]+(?:\\.[0-9]+)?s$") then
      capture("^(?:(?<hours>[0-9]+)h)?(?:(?<minutes>[0-9]+)m)?(?<seconds>[0-9]+(?:\\.[0-9]+)?)s$")
      | ((.hours // "0" | tonumber) * 3600) + ((.minutes // "0" | tonumber) * 60) + (.seconds | tonumber)
    elif test("^[0-9]+(?:\\.[0-9]+)?ms$") then (sub("ms$"; "") | tonumber) / 1000
    elif test("^[0-9]+(?:\\.[0-9]+)?(?:us|µs)$") then (sub("(?:us|µs)$"; "") | tonumber) / 1000000
    else error("ALLUXIO POSIX READ FAILED: unparseable elbencho duration \"\($text)\"")
    end;

# Input: the text of one elbencho result (read with jq -Rs). Takes the LAST DONE column, the
# total over all threads once the slowest finishes. A leading NOTE line, the Files* rows of
# directory mode and a trailing "Terminating due to phase time limit." line are tolerated.
# timed_out is true when elbencho stopped at its time limit, in which case the run is
# comparable by IOPS but its elapsed time is not a completion time. Latency fields are null
# when elbencho printed no latency rows (single-stream runs).
def parse_elbencho:
  . as $text
  | ($text | split("\n")) as $lines
  | def last_column($row_name):
      [$lines[] | (capture("^\\s*(?:READ\\s+)?" + $row_name + "\\s*:\\s*(?<first>\\S+)\\s+(?<last>\\S+)\\s*$")? | .last)];
    def percentile($name):
      [$lines[] | (capture("IO lat % us\\s*:.*\\b" + $name + "%<=(?<us>[0-9]+)")? | .us | tonumber)] | first;
    def required($row_name; $values):
      if ($values | length) == 0
      then error("ALLUXIO POSIX READ FAILED: elbencho result has no \($row_name) row (truncated output?)")
      else $values | last
      end;
    {
      elapsed_seconds: (required("Elapsed time"; last_column("Elapsed time")) | elbencho_seconds),
      iops: (required("IOPS"; last_column("IOPS")) | tonumber),
      mebibytes_per_second: (required("Throughput MiB/s"; last_column("Throughput MiB/s")) | tonumber),
      total_mebibytes: (required("Total MiB"; last_column("Total MiB")) | tonumber),
      latency_p50_us: percentile("50"),
      latency_p99_us: percentile("99"),
      timed_out: ($text | contains("Terminating due to phase time limit."))
    };

# Input: the text of one elbencho result. Returns the parsed result or fails. Every run must
# move data (iops > 0, total_mebibytes > 0). A "hot" run is requested for $rep_seconds, so
# anything under 0.9 * $rep_seconds means elbencho ended early. Other groups (e.g. "cold",
# which may stop at its time limit) ignore $rep_seconds.
def validate_elbencho_run($group; $rep_seconds):
  parse_elbencho
  | if .iops > 0 and .total_mebibytes > 0 and ($group != "hot" or .elapsed_seconds >= 0.9 * $rep_seconds)
    then .
    else error("ALLUXIO POSIX READ FAILED: elbencho run must have iops > 0, total_mebibytes > 0 and, for hot runs, elapsed_seconds >= 0.9 * the requested seconds (got \(.))")
    end;

# ---------------------------------------------------------------------------------------------
# Summaries, cache-hit proof and Blob egress. The Blob egress attribution and the median come
# from the S3 read pipeline (callers pass -L <repo>/kcl/alluxio).

def failed($message): error("ALLUXIO POSIX READ FAILED: " + $message);

# Input: a list of objects with a side. The sides present must be exactly $sides (sorted), so that a summary
# never silently leaves out a side whose results are missing.
def require_sides($sides):
  if (map(.side) | unique) == $sides then .
  else failed("expected the sides \($sides), got \(map(.side) | unique)")
  end;

def median_of: if length == 0 then failed("median of an empty list") else s3::median end;

def epoch: try fromdateiso8601 catch failed("bad ISO-8601 timestamp \(.)");

# Reps 1..$reps exactly: no missing, repeated or extra rep.
def require_reps($reps; $what):
  if (map(.rep) | sort) == [range(1; $reps + 1)]
  then .
  else failed("\($what) must have exactly reps 1 to \($reps), got \(map(.rep) | sort)")
  end;

# Input: {runs: [{scenario, side, rep, result}], blob_bytes_by_rep: [{side, scenario, rep, blob_bytes}]?}
# where result is a parse_elbencho object and side is "alluxio", "bf2" or "dacs". blob_bytes_by_rep is
# the optional output of concurrent_summary; it adds the Blob bytes per rep to the sides it covers.
# Each run may carry group "hot" or "cold" (default "cold"). Each side of a scenario must have exactly reps
# 1 to $reps (3 in a full run, 1 in a smoke run).
# Per side the medians (and ranges) of IOPS, MiB/s and the two latency percentiles are reported, and the
# elapsed time unless a rep stopped at its time limit (a time-limited run has no completion time).
# ratio_vs_bf2 and ratio_vs_dacs are Alluxio over the other side, so a value above 1 favours Alluxio, or null
# when a side is absent. They compare median IOPS (ratio_basis): the sides of a scenario read with the same block
# size, so this equals the throughput ratio, but elbencho prints MiB/s rounded to a whole number, which distorts
# the ratio of small-block reads (a few MiB/s), and IOPS also compares a cold rep that hit its time limit.
# timed_out_sides names the sides of a cold scenario that hit it. Hot runs always end with the time-limit line,
# so they never count as timed out. Output: one object per scenario, sorted.
def scenario_summary($reps):
  . as $input
  | $input.runs as $runs
  | ($input.blob_bytes_by_rep // []) as $blobs
  | def stat($values): {median: ($values | median_of), range: [($values | min), ($values | max)]};
    def optional_stat($values): if ($values | any(. == null)) then null else stat($values) end;
    def side_summary($scenario; $side):
      [$runs[] | select(.scenario == $scenario and .side == $side)] as $side_runs
      | ($side_runs | require_reps($reps; "scenario \($scenario) side \($side)") | map(.result)) as $results
      | ($results | any(.timed_out)) as $stopped
      | ($side_runs | any((.group // "cold") == "cold" and .result.timed_out)) as $timed_out
      | [$blobs[] | select(.scenario == $scenario and .side == $side)] as $blob_reps
      | {
          timed_out: $timed_out,
          iops: stat($results | map(.iops)),
          mebibytes_per_second: stat($results | map(.mebibytes_per_second)),
          elapsed_seconds: (if $stopped then null else stat($results | map(.elapsed_seconds)) end),
          latency_p50_us: optional_stat($results | map(.latency_p50_us)),
          latency_p99_us: optional_stat($results | map(.latency_p99_us))
        }
        + (if ($blob_reps | length) == 0 then {}
           else {blob_bytes: {
             reps: ($blob_reps | require_reps($reps; "Blob bytes of scenario \($scenario) side \($side)") | sort_by(.rep) | map({rep, blob_bytes})),
             median: ($blob_reps | map(.blob_bytes) | median_of)
           }} end);
    [$runs[] | .side] | unique as $present
  | if ($present - ["alluxio", "bf2", "dacs"]) != [] then failed("unknown side in \($present)") else . end
  | [$runs[] | .scenario] | unique
  | map(. as $scenario
      | ([$runs[] | select(.scenario == $scenario) | .side] | unique) as $sides
      | ([$sides[] as $side | {key: $side, value: side_summary($scenario; $side)}] | from_entries) as $by_side
      | ([$by_side | to_entries[] | select(.value.timed_out) | .key]) as $timed_out_sides
      | "iops" as $basis
      | def ratio($other):
          if $by_side.alluxio == null or $by_side[$other] == null then null
          elif $by_side[$other][$basis].median == 0 then failed("scenario \($scenario) side \($other) has a zero median \($basis)")
          else $by_side.alluxio[$basis].median / $by_side[$other][$basis].median
          end;
        {
          scenario: $scenario,
          ratio_basis: $basis,
          timed_out_sides: $timed_out_sides,
          ratio_vs_bf2: ratio("bf2"),
          ratio_vs_dacs: ratio("dacs"),
          sides: $by_side
        });

# The numeric samples of a Prometheus text exposition as [{name, labels, value}]. Comments, blank and
# unrelated lines are skipped by the caller's name filter; NaN and Inf samples are ignored. A trailing
# timestamp is allowed.
def prometheus_samples:
  [split("\n")[]
    | capture("^(?<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\\{(?<labels>[^}]*)\\})?\\s+(?<value>-?[0-9]+(?:\\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)(?:\\s+-?[0-9]+)?\\s*$")?
    | {name, labels: ((.labels // "") | gsub(",\\s+"; ",")), value: (.value | tonumber)}];

# Sum of one counter over all pods, or null when no pod reported it (a missing counter is not 0);
# $labels are exact label pairs such as "request_type=\"Download\"".
def counter_total($samples; $name; $labels):
  [$samples[]
    | select(.name == $name)
    | select(("," + .labels + ",") as $have | all($labels[]; . as $pair | $have | contains("," + $pair + ",")))
    | .value]
  | if length == 0 then null else add end;

# Input: {before, after}, Prometheus text with the metrics of every pod concatenated. Counters are
# summed over the pods and the before value is subtracted. A counter with no sample in before or in after
# is null, never 0: a missing counter must not pass as "nothing happened". A counter that went backwards
# (a restarted pod) fails: the difference would be meaningless. Alluxio counters are the workers' cache hit
# and miss calls and bytes read from the UFS; DACS counters are the server's successful Download and Upload
# requests.
def counter_delta:
  (.before | prometheus_samples) as $before
  | (.after | prometheus_samples) as $after
  | def delta($name; $labels):
      counter_total($before; $name; $labels) as $from
      | counter_total($after; $name; $labels) as $to
      | if $from == null or $to == null then null
        elif $to - $from < 0
        then failed("counter \($name) went backwards by \($from - $to) between the two snapshots (restarted pod?)")
        else $to - $from
        end;
    {
      alluxio_hit: delta("alluxio_cache_hit_calls_total"; []),
      alluxio_miss: delta("alluxio_cache_miss_calls_total"; []),
      alluxio_ufs_bytes: delta("alluxio_external_data_read_bytes_total"; []),
      dacs_download: delta("cache_server_request_counter"; ["request_type=\"Download\"", "status=\"Success\""]),
      dacs_upload: delta("cache_server_request_counter"; ["request_type=\"Upload\"", "status=\"Success\""])
    };

# Input: a counter_delta object over a hot phase plus hot_bytes, the SIZE OF THE HOT DATA SET (hot files x
# MiB per file), not the bytes read. Proves the cache served the reads instead of being bypassed: Alluxio
# must show cache hits and have fetched at most 1% of the hot data set from the UFS; DACS must show Download
# requests and have uploaded (refilled) at most 1% of the hot data set counted in 1 MiB blocks. Both
# counters of the side must be present (numbers): an absent counter fails.
def validate_cache_hits($side):
  . as $counters
  | def numbers($names): all($names[]; . as $name | ($counters[$name] | type) == "number");
    if ($counters.hot_bytes | type) != "number" or $counters.hot_bytes <= 0
    then failed("validate_cache_hits needs hot_bytes > 0")
    elif $side == "alluxio" then
      if (numbers(["alluxio_hit", "alluxio_ufs_bytes"]) | not)
      then failed("Alluxio hot run needs the alluxio_hit and alluxio_ufs_bytes counters; a counter is missing (workers not scraped?)")
      elif $counters.alluxio_hit > 0 and $counters.alluxio_ufs_bytes * 100 <= $counters.hot_bytes
      then $counters
      else failed("Alluxio hot run must show cache hits and at most 1% of the hot data set read from the UFS (hits \($counters.alluxio_hit), UFS bytes \($counters.alluxio_ufs_bytes), hot data set \($counters.hot_bytes)); the cache may have been bypassed")
      end
    elif $side == "dacs" then
      if (numbers(["dacs_download", "dacs_upload"]) | not)
      then failed("DACS hot run needs the Download and Upload counters; a counter is missing (servers not scraped?)")
      elif $counters.dacs_download > 0 and $counters.dacs_upload * 100 * 1048576 <= $counters.hot_bytes
      then $counters
      else failed("DACS hot run must show Download requests and at most 1% of the hot data set (in 1 MiB blocks) uploaded (downloads \($counters.dacs_download), uploads \($counters.dacs_upload), hot data set \($counters.hot_bytes)); the cache may have been bypassed")
      end
    else failed("validate_cache_hits side must be \"alluxio\" or \"dacs\", got \($side)")
    end;

# Input: {index, metrics}. index holds one {side, scenario, rep, start, end} per run (ISO-8601 UTC);
# metrics is the Azure Monitor Egress output with 1-minute totals. Every run of a side is indexed: the hot
# phase as ONE entry {scenario: "hot", rep: "all", start: first hot start, end: last hot end}, the cold reps
# ("21-22"), the concurrent reps ("23-24", one entry per client), the re-read reads ("29", reps 1 and 2).
# Egress is attributed one side at a time, over only that side's runs, so the last window of one side never
# absorbs the next phase; within a side the scenario and rep are keyed "<scenario>/<rep>" so that reps of
# different scenarios cannot collide.
# Each group owns the buckets from its own first bucket to the next group's first bucket (see
# s3::attribute_egress), so a group is not charged for later traffic only because every run of a side is
# indexed, the pipeline leaves at least 70 s between groups and at least 120 s after the warm-up; the last
# group of a side also owns 3 trailing minutes, so nothing unindexed may follow it. A bucket with a total of
# 0 counts as a data point (an idle minute is real); the lower bounds of concurrent_summary guard against a
# late metric reading 0.
# The warm-up is its own group {scenario: "warmup", rep: "all"}, so its late buckets are not charged to the hot
# phase. The two re-read reads (scenario "29", reps 1 and 2) are separate groups with at least 70 s between them;
# re-read runs are never passed to scenario_summary.
# Output: [{side, scenario, rep, blob_bytes}] sorted by side, scenario, then rep (numeric reps in numeric order,
# then "all"). A group without any Egress data point fails, and so does a single hot run (group "hot" with a
# numeric rep) or a hot entry whose rep is not "all": each would cut the hot phase into windows of its own.
def blob_egress_by_rep:
  . as $input
  | [$input.index[] | select((.group == "hot" or .scenario == "hot") and .rep != "all") | .label // "\(.side) \(.scenario)/\(.rep)"] as $single
  | if ($single | length) > 0
    then failed("scenario hot requires rep all: pass the one hot entry per side, not the single hot runs \($single)")
    else .
    end
  | [($input.index | map(.side) | unique[]) as $side
    | {
        index: [$input.index[] | select(.side == $side) | .rep = "\(.scenario)/\(.rep)"],
        metrics: $input.metrics
      }
    | (try s3::attribute_egress catch failed(.))[]
    | (.rep | capture("^(?<scenario>[^/]+)/(?<rep>.+)$")) as $key
    | {side, scenario: $key.scenario, rep: ($key.rep | if test("^[0-9]+$") then tonumber else . end), blob_bytes}]
  | sort_by([.side, .scenario, (.rep | if type == "number" then [0, .] else [1, .] end)]);

# Input: {index, metrics, hot_bytes}; index and metrics as for blob_egress_by_rep, hot_bytes the size of the
# hot data set (hot files x MiB per file), not the bytes read. Every cache side (alluxio, dacs) in the index must
# have exactly one hot entry {scenario: "hot", rep: "all"}: without it the check below could not run, which
# fails instead of passing silently. The Blob bytes of the hot phase of a cache side must not exceed 1% of the
# hot data set: more means the cache was bypassed while the hot reads ran, which the server counters alone
# cannot show. BlobFuse2 is reported only, and the warm-up group has no bound (it is expected to load the cache).
# Output: {hot_blob_bytes: [{side, blob_bytes, hot_bytes}], warmup_blob_bytes: [{side, blob_bytes}]}.
def hot_egress_summary:
  . as $input
  | (if (.hot_bytes | type) != "number" or .hot_bytes <= 0 then failed("hot_egress_summary needs hot_bytes > 0") else . end)
  | ([.index[] | select(.side != "bf2") | .side] | unique) as $cache_sides
  | ([$cache_sides[] as $side
      | select([$input.index[] | select(.side == $side and .scenario == "hot" and .rep == "all")] | length != 1)
      | $side]) as $without_hot
  | if ($without_hot | length) > 0
    then failed("the index needs exactly one hot entry (scenario \"hot\", rep \"all\") for each cache side, missing or repeated for \($without_hot)")
    else .
    end
  | blob_egress_by_rep as $egress
  | {
      hot_blob_bytes: [$egress[] | select(.scenario == "hot")
        | if .side != "bf2" and .blob_bytes * 100 > $input.hot_bytes
          then failed("Blob egress for \(.side) during the hot reads is \(.blob_bytes) bytes, above 1% of the \($input.hot_bytes) byte hot data set; cache bypassed during hot reads")
          else {side, blob_bytes, hot_bytes: $input.hot_bytes}
          end],
      warmup_blob_bytes: [$egress[] | select(.scenario == "warmup") | {side, blob_bytes}]
    };

# Input: {index, metrics, counters, hot_bytes?}. index and metrics as for blob_egress_by_rep; counters is
# [{side, rep, alluxio_ufs_bytes}], the workers' UFS-read difference for each Alluxio rep of the concurrent
# scenario "23-24". Each side must have exactly reps 1 to $reps of it, and each rep exactly $clients client
# runs, each reading the same $client_bytes (the smoke run uses fewer clients and a smaller file than the full
# one). Sanity bounds on the attributed Blob bytes of each concurrent rep:
# - BlobFuse2 reads from Blob directly: at least $clients x $client_bytes x 0.95.
# - A cache (Alluxio, DACS) fetches one copy: at least $client_bytes x 0.95. DACS has no upper bound.
# - Alluxio must stay within 0.95 to 1.05 x its workers' UFS count: less means a late or partial metric, more
#   means other traffic on the account was counted.
# slowest_client_seconds is the longest start-to-end time of a rep's clients; completion_spread_seconds is the
# gap between the first and last client to end. blob_bytes_by_rep is every group of every scenario (cold, hot,
# warm-up, re-read included) for scenario_summary and reread_summary. hot_bytes is required: hot_blob_bytes and
# warmup_blob_bytes come from hot_egress_summary, which fails when a cache side has no hot entry or its Blob
# bytes during the hot reads show the cache was bypassed.
def concurrent_summary($reps; $clients; $client_bytes):
  . as $input
  | blob_egress_by_rep as $egress
  | def worker_ufs($rep):
      [$input.counters[]? | select(.side == "alluxio" and .rep == $rep) | .alluxio_ufs_bytes][0];
    def check_bounds($side):
      if $side == "bf2" and .blob_bytes < $clients * $client_bytes * 0.95
      then failed("Blob egress for bf2 rep \(.rep) is \(.blob_bytes) bytes, below the \($clients) x \($client_bytes) the clients read; the metric is late or partial")
      elif $side != "bf2" and .blob_bytes < $client_bytes * 0.95
      then failed("Blob egress for \($side) rep \(.rep) is \(.blob_bytes) bytes, below the \($client_bytes) one copy needs; the metric is late or partial")
      elif $side == "alluxio" and worker_ufs(.rep) == null
      then failed("no worker UFS counter for alluxio rep \(.rep)")
      elif $side == "alluxio" and .blob_bytes < 0.95 * worker_ufs(.rep)
      then failed("Blob egress for alluxio rep \(.rep) is \(.blob_bytes) bytes, below 95% of the \(worker_ufs(.rep)) bytes the workers read from Blob; the metric is late or partial")
      elif $side == "alluxio" and .blob_bytes > 1.05 * worker_ufs(.rep)
      then failed("Blob egress for alluxio rep \(.rep) is \(.blob_bytes) bytes, more than 5% above the \(worker_ufs(.rep)) bytes the workers read from Blob; other traffic on the account was counted")
      else .
      end;
    ([$input.index[] | select(.scenario == "23-24") | .side] | unique) as $sides
  | if ($sides | length) == 0 then failed("no concurrent (23-24) runs in the index") else . end
  | {
      scenario: "23-24",
      sides: ([$sides[] as $side
        | {
            key: $side,
            value: ([$egress[] | select(.side == $side and .scenario == "23-24")]
              | require_reps($reps; "concurrent side \($side)")
              | map(check_bounds($side) | . as $rep
                | [$input.index[] | select(.side == $side and .scenario == "23-24" and .rep == $rep.rep)] as $runs
                | if ($runs | length) != $clients
                  then failed("concurrent side \($side) rep \($rep.rep) has \($runs | length) client runs, expected \($clients)")
                  else {
                    rep: $rep.rep,
                    blob_bytes: $rep.blob_bytes,
                    clients: ($runs | length),
                    slowest_client_seconds: ($runs | map((.end | epoch) - (.start | epoch)) | max),
                    completion_spread_seconds: (($runs | map(.end | epoch) | max) - ($runs | map(.end | epoch) | min))
                  }
                  + (if $side == "alluxio" then {worker_ufs_bytes: worker_ufs($rep.rep)} else {} end)
                  end))
          }] | from_entries),
      blob_bytes_by_rep: $egress
    }
  + ($input | hot_egress_summary);

# Input: {first, second, side, counters, blob_bytes_by_rep}. first and second are parse_elbencho results of
# two reads of the same file; side ("alluxio", "bf2" or "dacs") is required. For the Alluxio side counters is
# required: {before, between, after}, Prometheus text snapshots (as for counter_delta) taken before the first
# read, between the reads and after the second, containing the Alluxio UFS counter; a missing counters object,
# snapshot or counter fails. Other sides have no Alluxio counters and report null UFS bytes. blob_bytes_by_rep,
# from concurrent_summary, is optional; with it the Blob bytes of the side's scenario "29" reps 1 and 2 are
# reported (the reads are indexed per side as separate egress groups, at least 70 s apart). Reports the MiB/s of
# both reads and the Alluxio UFS bytes each one caused; the second should be near 0.
def reread_summary:
  . as $input
  | (["alluxio", "bf2", "dacs"] | any(. == $input.side)) as $known
  | if ($known | not) then failed("reread_summary needs side \"alluxio\", \"bf2\" or \"dacs\", got \($input.side)")
    elif $input.side == "alluxio" and ([($input.counters // {}) | .before, .between, .after] | all(type == "string") | not)
    then failed("reread_summary for alluxio needs counters with before, between and after snapshots")
    else .
    end
  | def ufs($from; $to):
      if $input.side != "alluxio" then null
      else ({before: $input.counters[$from], after: $input.counters[$to]} | counter_delta | .alluxio_ufs_bytes)
        | if . == null then failed("re-read counters lack alluxio_external_data_read_bytes_total") else . end
      end;
    def blob($rep):
      if $input.blob_bytes_by_rep == null then null
      else ([$input.blob_bytes_by_rep[] | select(.side == $input.side and .scenario == "29" and .rep == $rep) | .blob_bytes][0])
        | if . == null then failed("no Blob bytes for \($input.side) re-read \($rep)") else . end
      end;
    {
      first_mebibytes_per_second: $input.first.mebibytes_per_second,
      second_mebibytes_per_second: $input.second.mebibytes_per_second,
      first_alluxio_ufs_bytes: ufs("before"; "between"),
      second_alluxio_ufs_bytes: ufs("between"; "after"),
      first_blob_bytes: blob(1),
      second_blob_bytes: blob(2)
    };

# The data set the benchmark reads: every file of the container as {name, bytes}, flat, without directories.
# The generator writes exactly these files and the verification expects exactly these, so the names and sizes
# have one owner. One hot pool p000.. shared by every side (each side reads it into its own cache, or, without a
# cache, reads it the same way in every rep). $sides is {cold, concurrent, reread}, the sides of each of those
# scenarios: every one of these sides gets its own cold sets <side>-cold-r1 to r3, concurrent-read sets
# <side>-cc-r1 to r3 and re-read file <side>-m8, so no side reads a blob that another side read before it.
def posix_dataset($hot_files; $hot_mib; $cold_files; $cc_files; $big_gib; $reread_gib; $sides):
  def pad($width): ("0000" + tostring)[-$width:];
  if ($sides | type) != "object" or ([$sides.cold, $sides.concurrent, $sides.reread] | any(type != "array"))
  then failed("posix_dataset needs the sides as {cold, concurrent, reread} lists, got \($sides)")
  else
    [range(0; $hot_files) | {name: ("p" + pad(3)), bytes: ($hot_mib * 1048576)}]
    + [$sides.cold[] as $side | range(1; 4) as $rep | range(0; $cold_files)
      | {name: ("\($side)-cold-r\($rep)-" + pad(2)), bytes: ($big_gib * 1073741824)}]
    + [$sides.concurrent[] as $side | range(1; 4) as $rep | range(0; $cc_files)
      | {name: ("\($side)-cc-r\($rep)-" + pad(2)), bytes: ($big_gib * 1073741824)}]
    + [$sides.reread[] as $side | {name: "\($side)-m8", bytes: ($reread_gib * 1073741824)}]
  end;

# Input: `az storage blob list --include m` of the container. It must hold exactly the files of
# posix_dataset with their sizes and no directory marker (an hdi_isfolder blob or a name ending in "/").
def validate_posix_dataset($hot_files; $hot_mib; $cold_files; $cc_files; $big_gib; $reread_gib; $sides):
  posix_dataset($hot_files; $hot_mib; $cold_files; $cc_files; $big_gib; $reread_gib; $sides) as $expected
  | if type != "array" then failed("the Blob listing is not a list")
    elif s3::count_directory_markers != 0 then failed("the container holds directory markers; the data must be flat files")
    elif length != ($expected | length) then failed("the container holds \(length) blobs, expected \($expected | length)")
    elif ([.[] | {name, bytes: .properties.contentLength}] | sort_by(.name)) != ($expected | sort_by(.name))
    then failed("the container's blob names or sizes differ from the data set")
    else .
    end;
