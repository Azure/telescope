# A directory marker is a blob whose name ends in "/" or that carries the
# hdi_isfolder metadata (requires `az storage blob list --include m`).
# abfs v2 would otherwise treat such a marker as a file.
def count_directory_markers:
  [.[] | select((.name | endswith("/")) or (.metadata.hdi_isfolder == "true"))] | length;

def validate_s3_read_dataset:
  [range(0; 16) | "object-" + (if . < 10 then "0" else "" end) + tostring + ".bin"] as $big_names
  | [range(0; 1024) | "small/obj-" + ("0000" + tostring | .[-4:]) + ".bin"] as $small_names
  | if type == "array" and length == 1040
       and count_directory_markers == 0
       and ([.[] | select(.name | startswith("small/") | not)] | map(.name) | sort) == $big_names
       and ([.[] | select(.name | startswith("small/"))] | map(.name) | sort) == $small_names
       and all(.[] | select(.name | startswith("small/") | not); .properties.contentLength == 67108864)
       and all(.[] | select(.name | startswith("small/")); .properties.contentLength == 1048576)
    then .
    else error("Blob dataset must contain exactly 16 objects of 64 MiB and 1024 small/ objects of 1 MiB, with no directory markers")
    end;

# Input: the checkpoint container as a list of {name, properties: {contentLength}, metadata}.
# It must hold exactly set-1..6 x part-0..7 (48 objects) of 2 GiB (2147483648 bytes) and no directory markers.
def validate_checkpoint_dataset:
  [range(1; 7) as $set | range(0; 8) as $part | "set-\($set)/part-\($part).bin"] as $names
  | if type == "array"
       and (map(.name) | sort) == ($names | sort)
       and count_directory_markers == 0
       and all(.[]; .properties.contentLength == 2147483648)
    then .
    else error("Checkpoint container must hold exactly 48 objects of 2147483648 bytes (set-1..6 x part-0..7) and no directory markers")
    end;

# One s3c.sh result line. s3c.sh already exits non-zero on errors; this re-checks the
# artifact itself so a result that was edited or truncated cannot pass.
# new_connections (ok requests that opened a connection despite the warm-up) is reported, not judged.
def validate_s3c_run:
  if type == "object"
     and .err == 0
     and (.ok | type == "number" and . > 0)
     and (.bytes | type == "number" and . > 0)
     and (.retries | type == "number" and . >= 0)
     and (.failures | type == "object")
     and (.new_connections | type == "number" and . >= 0)
     and (.max_time_seconds | type == "number" and . > 0)
     # Timed runs request 60 s and stop starting batches then. The batch in flight can still run: 30 s
     # covers the rest of a batch (the pipeline sizes batches to finish within about 23 s), and one request
     # that retries can take up to about twice max_time_seconds (see s3c.sh).
     and (.kind == "onepass" or (.max_time_seconds as $max_time | .wall_seconds | type == "number" and . >= 55 and . <= 90 + 2 * $max_time))
  then .
  else error("S3 read run must have err 0, ok > 0, bytes > 0, retries >= 0, new_connections >= 0, max_time_seconds > 0, a failures object and, for timed runs, wall_seconds in [55, 90 + 2 * max_time_seconds]")
  end;

# Input: an Alluxio s3c.sh result for a preloaded dataset. $ufs_bytes is how much the workers' UFS-read
# counter grew during the run. A read served from the cache reads nothing from Blob, so more than 1% of
# the bytes the clients read means reads went to Blob; a negative value means a worker restarted.
def served_from_cache($ufs_bytes):
  $ufs_bytes >= 0 and $ufs_bytes <= 0.01 * .bytes;

# Input: the text of `alluxio fs check-cached --recursive` (read with jq -Rs) for a mount
# holding the 1,040-object dataset (16 big + 1,024 small). Every file must be fully cached.
def validate_all_cached:
  . as $report
  | {
      total: "Total files checked",
      all: "Fully cached on all replicas files count",
      one: "Fully cached on at least 1 replica files count",
      partial: "Partially cached files count",
      uncached: "Not cached files count",
      failed: "Failed files count"
    }
  | with_entries(
      .value as $field_name
      | .value = ($report | capture("(?m)^\\s*" + $field_name + ":\\s*(?<count>[0-9]+)\\s*$").count | tonumber)
    )
  | if .total == 1040 and .all == 1040 and .one == 0 and .partial == 0 and .uncached == 0 and .failed == 0
    then .
    else error("All 1040 dataset files must be fully cached on all replicas")
    end;

# az may print timeStamp as ...Z, ...+00:00 or with fractional seconds; fromdateiso8601 only takes the plain Z form.
def azure_epoch: sub("\\+00:00$"; "Z") | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601;

def minute_start: (. / 60 | floor) * 60;

def median:
  sort as $sorted
  | ($sorted | length) as $count
  | if $count == 0 then error("median of an empty list")
    elif $count % 2 == 1 then $sorted[($count - 1) / 2]
    else ($sorted[$count / 2 - 1] + $sorted[$count / 2]) / 2
    end;

# Input: {index, metrics}. index holds one {side, rep, pod, start, end} per client run (ISO-8601 UTC);
# metrics is the `az monitor metrics list` output for Egress with 1-minute totals.
# Azure Monitor reports a minute about one minute late, so a run's first bucket is the minute after its
# earliest start: minute_start(earliest start) + 60 s. The (side, rep) groups are ordered by that start and
# the windows are contiguous: each group owns the buckets from its own first bucket up to, but excluding,
# the next group's first bucket. Egress is recorded after the client has finished and can spill into later
# minutes, so the spill stays with the run that caused it; no bucket between two runs belongs to nobody.
# Consecutive runs start at least 70 s apart in the pipeline, so their first buckets differ and no bucket
# is counted twice. The last group owns the buckets up to minute_start(latest end) + 60 s plus 3 trailing
# minutes, because the final egress has nothing after it to bound it. A window with no data point carrying
# a "total" is an error, never 0. Output: [{side, rep, blob_bytes}] sorted by side, rep.
def attribute_egress:
  [.metrics.value[0].timeseries[]?.data[]?
    | select(.total != null)
    | {at: (.timeStamp | azure_epoch), total: .total}] as $points
  | [.index | group_by([.side, .rep])[]
    | {
        side: .[0].side,
        rep: .[0].rep,
        from: (((map(.start | fromdateiso8601) | min) | minute_start) + 60),
        last_end: (((map(.end | fromdateiso8601) | max) | minute_start) + 60)
      }]
  | sort_by(.from) as $ordered
  | [range(0; $ordered | length) as $i
    | $ordered[$i]
    | . as $window
    | (if $i + 1 < ($ordered | length)
       then {to: $ordered[$i + 1].from, inclusive: false}
       else {to: ($window.last_end + 180), inclusive: true}
       end) as $limit
    | [$points[] | select(.at >= $window.from and (if $limit.inclusive then .at <= $limit.to else .at < $limit.to end)) | .total] as $totals
    | if ($totals | length) == 0
      then error("No Egress data point for \($window.side) rep \($window.rep); the metric is late or missing")
      else {side: $window.side, rep: $window.rep, blob_bytes: ($totals | add)}
      end]
  | sort_by([.side, .rep]);

# Input: {index, metrics, runs, worker_ufs}. runs is one {side, rep, pod, wall_seconds, retries} per client run;
# worker_ufs is [{rep, bytes}], the Alluxio workers' UFS-read counter difference for each Alluxio rep.
# Each side must have exactly 3 reps. completion_spread_seconds is the gap between the first and
# last pod to finish (from index ends). Ratios use the medians over the 3 reps; both are oriented so
# that a value above 1 favours Alluxio: blob_bytes_ratio is Blob egress / Alluxio egress and
# completion_speedup is the slowest Blob client's time / the slowest Alluxio client's time.
# retries is the sum of the request retries over the rep's clients.
#
# Sanity bounds on the attributed egress, per rep. One client reads 8 x 2 GiB = 17179869184 bytes,
# and the 5 clients together read 5 times that.
# - Blob side: every client reads straight from Blob, so the account must serve at least 5 x 17179869184.
# - Alluxio side: the workers must have fetched at least one copy (17179869184), and Blob must have
#   served at least 95% of what the workers counted as read from the UFS.
# An undercount means a late or partial metric, which would otherwise be reported as a result.
def checkpoint_summary:
  . as $input
  | attribute_egress as $egress
  | def worker_ufs_bytes($rep): [$input.worker_ufs[] | select(.rep == $rep) | .bytes][0];
    def check_bounds($side):
      if $side == "blob" and .blob_bytes < 5 * 17179869184
      then error("Blob egress for blob rep \(.rep) is \(.blob_bytes) bytes, below the 5 x 17179869184 the clients read; the metric is late or partial")
      elif $side == "alluxio" and .blob_bytes < 17179869184
      then error("Blob egress for alluxio rep \(.rep) is \(.blob_bytes) bytes, below the 17179869184 the workers must fetch; the metric is late or partial")
      elif $side == "alluxio" and .blob_bytes < 0.95 * worker_ufs_bytes(.rep)
      then error("Blob egress for alluxio rep \(.rep) is \(.blob_bytes) bytes, below 95% of the \(worker_ufs_bytes(.rep)) bytes the workers read from Blob; the metric is late or partial")
      # More than 5% above what the workers read means other traffic on the account was counted (the
      # Alluxio reps move little data, so earlier traffic would distort them most).
      elif $side == "alluxio" and .blob_bytes > 1.05 * worker_ufs_bytes(.rep)
      then error("Blob egress for alluxio rep \(.rep) is \(.blob_bytes) bytes, more than 5% above the \(worker_ufs_bytes(.rep)) bytes the workers read from Blob; other traffic on the account was counted")
      else .
      end;
    def side_reps($side):
      [$egress[] | select(.side == $side)] as $reps
      | if ($reps | map(.rep) | sort) != [1, 2, 3]
        then error("Side \($side) must have exactly reps 1, 2 and 3")
        else [$reps[] | check_bounds($side) | . as $rep
          | [$input.index[] | select(.side == $side and .rep == $rep.rep) | .end | fromdateiso8601] as $ends
          | {
              rep: $rep.rep,
              blob_bytes: $rep.blob_bytes,
              slowest_client_seconds: ([$input.runs[] | select(.side == $side and .rep == $rep.rep) | .wall_seconds] | max),
              retries: ([$input.runs[] | select(.side == $side and .rep == $rep.rep) | .retries] | add),
              completion_spread_seconds: (($ends | max) - ($ends | min))
            }
          + (if $side == "alluxio"
             then {worker_ufs_bytes: worker_ufs_bytes($rep.rep)}
             else {} end)]
        end;
  side_reps("alluxio") as $alluxio
  | side_reps("blob") as $blob
  | {
      alluxio: $alluxio,
      blob: $blob,
      blob_bytes_ratio: (($blob | map(.blob_bytes) | median) / ($alluxio | map(.blob_bytes) | median)),
      completion_speedup: (($blob | map(.slowest_client_seconds) | median) / ($alluxio | map(.slowest_client_seconds) | median))
    };

# Input: one object per scenario 1-10 run, the runs/index.jsonl entry {id, name, kind, dataset, concurrency,
# rangeBytes, side, rep, start, end}, plus worker_ufs {before, after, bytes} on the alluxio side, merged with
# that run's s3c.sh result (runs/<id>-<side>-<rep>.json).
# Every id needs exactly reps 1, 2 and 3 on both the alluxio and the blob side.
# Output: [{id, name, kind, dataset, concurrency, rangeBytes, alluxio, blob, retries, new_connections,
# worker_ufs_bytes, throughput_ratio, ttfb_p99_ratio, latency_p99_ratio}] sorted by id. alluxio and blob hold the
# median over the 3 reps of each metric; retries and new_connections hold, per side, the sums over the 3 reps.
# worker_ufs_bytes lists, for Alluxio reps 1-3, what the workers read from Blob during the rep; every rep is
# re-checked with served_from_cache.
# Throughput ratio is alluxio / blob (higher is better for Alluxio); the latency ratios are blob / alluxio,
# so a value above 1 favours Alluxio.
def scenario_summary:
  def cache_hit_bytes:
    if (.worker_ufs.bytes | type) == "number" and served_from_cache(.worker_ufs.bytes)
    then .worker_ufs.bytes
    else error("Scenario \(.id) alluxio rep \(.rep) must record worker_ufs.bytes of at most 1% of its \(.bytes) bytes")
    end;
  def side_median($runs; $id; $side):
    [$runs[] | select(.id == $id and .side == $side)] as $reps
    | if ($reps | map(.rep) | sort) != [1, 2, 3]
      then error("Scenario \($id) side \($side) must have exactly reps 1, 2 and 3")
      else
        ["mebibytes_per_second", "operations_per_second", "ttfb_p50_ms", "ttfb_p99_ms", "latency_p50_ms", "latency_p99_ms"]
        | map(. as $metric | {key: $metric, value: ($reps | map(.[$metric]) | median)})
        | from_entries
      end;
  . as $runs
  | [$runs[].id] | unique
  | map(. as $id
      | side_median($runs; $id; "alluxio") as $alluxio
      | side_median($runs; $id; "blob") as $blob
      | ([$runs[] | select(.id == $id)][0]) as $first
      | {
          id: $id,
          name: $first.name,
          kind: $first.kind,
          dataset: $first.dataset,
          concurrency: $first.concurrency,
          rangeBytes: $first.rangeBytes,
          alluxio: $alluxio,
          blob: $blob,
          retries: {
            alluxio: ([$runs[] | select(.id == $id and .side == "alluxio") | .retries] | add),
            blob: ([$runs[] | select(.id == $id and .side == "blob") | .retries] | add)
          },
          new_connections: {
            alluxio: ([$runs[] | select(.id == $id and .side == "alluxio") | .new_connections] | add),
            blob: ([$runs[] | select(.id == $id and .side == "blob") | .new_connections] | add)
          },
          worker_ufs_bytes: ([$runs[] | select(.id == $id and .side == "alluxio")] | sort_by(.rep) | map(cache_hit_bytes)),
          throughput_ratio: ($alluxio.mebibytes_per_second / $blob.mebibytes_per_second),
          ttfb_p99_ratio: ($blob.ttfb_p99_ms / $alluxio.ttfb_p99_ms),
          latency_p99_ratio: ($blob.latency_p99_ms / $alluxio.latency_p99_ms)
        });
