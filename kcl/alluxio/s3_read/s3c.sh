#!/bin/sh
# Identical curl client for Alluxio's S3 API (MODE=alluxio) and Azure Blob REST (MODE=blob).
# Runs in curlimages/curl 8.9.0 or later (busybox sh and awk). Prints one JSON line on stdout.
#
#   KIND=get      CONCURRENCY workers GET random keys for DURATION_SECONDS
#   KIND=range    like get, each request reads RANGE_BYTES at a random 4096-aligned offset inside OBJECT_BYTES
#   KIND=onepass  every key is read exactly once, split over CONCURRENCY workers
#
# The keys are printf KEY_FORMAT with 0 .. KEY_COUNT - 1, for example object-%02d.bin and 16.
# Required: MODE KIND CONCURRENCY KEY_FORMAT KEY_COUNT BATCH_REQUESTS OBJECT_BYTES (the size of every object)
#   get/range:     DURATION_SECONDS
#   range:         RANGE_BYTES
#   MODE=blob:     ACCOUNT CONTAINER SAS_FILE
#   MODE=alluxio:  HOSTS (comma-separated host:port, exactly EXPECTED_HOSTS of them) EXPECTED_HOSTS BUCKET
# Optional: BLOB_ENDPOINT (default https://${ACCOUNT}.blob.core.windows.net) points the blob side at another server.
#           MAX_REQUESTS_PER_WORKER (default 20000) caps the requests prepared per worker for get/range.
#           CURL_MAX_TIME seconds allowed per attempt of a request (default 30 for get/range; for onepass 120,
#             or 1800 when a request moves more than 64 MiB). The result reports it as max_time_seconds.
#           HOST_OFFSET (default 0, MODE=alluxio) shifts which host each request goes to. Clients that read the
#             same keys at the same time pass different offsets so they do not all send a key to the same host.
#
# Every request, on both sides, is retried up to 3 times with curl's default backoff, which honors
# Retry-After. Azure Blob clients (the Azure SDK, BlobFuse2, azcopy) retry transient errors by default too.
# curl retries a transfer error such as a body cut short or a connect timeout, and HTTP 408, 429, 500, 502,
# 503 and 504; any other status, such as 403 or 404, is not retried. retry-max-time equals max-time, so an
# attempt that hits max-time is not retried, and no retry starts once max-time has passed since the first
# attempt. A retry that starts just before then still gets a full max-time, so one request, retries included,
# ends within about twice max-time. A retried request reports the timings and size of its last attempt, so the
# time spent on earlier attempts lowers the throughput but not the latency percentiles.
#
# Each curl run first sends an unmeasured HEAD to every host its measured requests will use, so the measured
# requests reuse a connection that is already open: without it, the first request of every run would also pay
# for DNS, TCP and, on the Blob side, TLS, while on the Alluxio side it opens a plain in-cluster TCP connection.
# A HEAD returns only the object's metadata, so it neither loads data into Alluxio's cache nor reads object
# data from Blob. The result's new_connections counts the ok requests that still opened a connection.
#
# A request counts as ok only if, after its retries, it returned 206 with RANGE_BYTES bytes (KIND=range) or
# 200 with OBJECT_BYTES bytes (get, onepass). Anything else, including a timeout, counts as err. Only the
# measured requests count; a warm-up HEAD that fails changes nothing but the connection reuse.
# The result has retries, the sum of every request's retries, and failures, which counts the failed requests
# by "<HTTP status> <bytes received>" (000 when no response arrived) and the curl runs that exited non-zero
# under "curl_exit"; it is {} when nothing failed.
# Exit status is 0 only if err is 0 and at least one request succeeded;
# otherwise ALLUXIO S3 READ FAILED: is written to stderr.
set -u

fail() {
  echo "ALLUXIO S3 READ FAILED: $*" >&2
  exit 1
}
require() {
  for variable_name in "$@"; do
    eval "variable_value=\${$variable_name:-}"
    [ -n "$variable_value" ] || fail "required variable $variable_name is not set"
  done
}

require MODE KIND CONCURRENCY KEY_FORMAT KEY_COUNT BATCH_REQUESTS OBJECT_BYTES
case $MODE in
  blob)
    require ACCOUNT CONTAINER SAS_FILE
    [ -s "$SAS_FILE" ] || fail "SAS_FILE $SAS_FILE is missing or empty"
    ;;
  alluxio)
    require HOSTS EXPECTED_HOSTS BUCKET
    host_count=$(echo "$HOSTS" | awk -F, '{print NF}')
    [ "$host_count" -eq "$EXPECTED_HOSTS" ] || fail "HOSTS lists $host_count hosts, expected $EXPECTED_HOSTS: $HOSTS"
    ;;
  *) fail "MODE must be alluxio or blob, got $MODE" ;;
esac
case $KIND in
  get) require DURATION_SECONDS ;;
  range) require DURATION_SECONDS RANGE_BYTES ;;
  onepass) ;;
  *) fail "KIND must be get, range or onepass, got $KIND" ;;
esac

MAX_REQUESTS_PER_WORKER=${MAX_REQUESTS_PER_WORKER:-20000}
if [ "$KIND" = range ]; then
  request_bytes=$RANGE_BYTES
  expected_status=206
else
  request_bytes=$OBJECT_BYTES
  expected_status=200
fi
# A timed run stops starting batches at DURATION_SECONDS, but a request it has started may still retry, so
# its wall time can exceed DURATION_SECONDS by up to about twice max-time (see the header); checks.jq allows
# for that. 30 s keeps that overrun short yet is more than 5 times the slowest p99 latency seen in a full run
# (5.7 s, a cross-region 64 MiB GET from Blob at 16 concurrent requests). A onepass run has no window:
# 120 s lets a 64 MiB request finish at about 0.5 MiB/s, and the 2 GiB checkpoint objects get 1800 s
# (about 1.2 MiB/s). CURL_MAX_TIME is exported for the awk program that writes every request's config.
if [ "$KIND" != onepass ]; then
  default_max_time=30
elif [ "$request_bytes" -gt 67108864 ]; then
  default_max_time=1800
else
  default_max_time=120
fi
export CURL_MAX_TIME=${CURL_MAX_TIME:-$default_max_time}
HOST_OFFSET=${HOST_OFFSET:-0}
export BLOB_BASE_URL=${BLOB_ENDPOINT:-https://${ACCOUNT:-}.blob.core.windows.net}
export SAS_QUERY=""
[ "$MODE" = blob ] && SAS_QUERY=$(cat "$SAS_FILE")

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT   # the per-request configs embed the SAS query
awk -v format="$KEY_FORMAT" -v count="$KEY_COUNT" 'BEGIN { for (key = 0; key < count; key++) printf format "\n", key }' > "$work_dir/keys"
[ -s "$work_dir/keys" ] || fail "KEY_COUNT must be a positive number, got $KEY_COUNT"

# One curl config per batch of BATCH_REQUESTS requests (all of a worker's keys for onepass). A batch is collected
# first, so that its config can start with the warm-up HEADs for the hosts the batch uses.
for worker in $(seq 1 "$CONCURRENCY"); do
  awk -v worker="$worker" -v worker_count="$CONCURRENCY" -v mode="$MODE" -v kind="$KIND" \
      -v max_requests="$MAX_REQUESTS_PER_WORKER" -v batch="$BATCH_REQUESTS" -v work_dir="$work_dir" \
      -v object_bytes="${OBJECT_BYTES:-0}" -v range_bytes="${RANGE_BYTES:-0}" -v host_offset="$HOST_OFFSET" \
      -v container="${CONTAINER:-}" -v bucket="${BUCKET:-}" -v hosts="${HOSTS:-}" '
    BEGIN { srand(worker * 7919 + 1); host_count = split(hosts, host_list, ","); blob_base = ENVIRON["BLOB_BASE_URL"] }
    { keys[NR] = $0 }
    END {
      key_count = NR
      if (kind == "onepass") {
        for (key_index = 1; key_index <= key_count; key_index++)
          if ((key_index - 1) % worker_count == worker - 1) add_request(keys[key_index], "", key_index - 1)
        write_batch(work_dir "/config" worker)
      } else {
        for (request = 0; request < max_requests; request++) {
          key = keys[int(rand() * key_count) + 1]
          byte_range = ""
          if (kind == "range") {
            offset = int(rand() * ((object_bytes - range_bytes) / 4096)) * 4096
            byte_range = offset "-" (offset + range_bytes - 1)
          }
          # Round-robin over the hosts; the worker number staggers the workers so they do not all hit one host at once.
          add_request(key, byte_range, request + worker - 1)
          if (request_count == batch) write_batch(work_dir "/config" worker "." int(request / batch))
        }
        write_batch(work_dir "/config" worker "." int((max_requests - 1) / batch))
      }
    }
    function add_request(key, byte_range, host_index) {
      request_count++
      request_key[request_count] = key
      request_range[request_count] = byte_range
      request_host[request_count] = host_index + host_offset
    }
    # Writes the collected requests to config_file: first one HEAD per distinct host, for the first key that
    # host serves, then the measured requests. curl keeps at most 5 idle connections in a run and has no
    # option to raise that, so with more than 5 hosts some measured requests reconnect; new_connections shows it.
    function write_batch(config_file,   request, host) {
      if (request_count == 0) return
      split("", warmed)
      for (request = 1; request <= request_count; request++) {
        host = (mode == "blob") ? blob_base : host_list[request_host[request] % host_count + 1]
        if (!(host in warmed)) {
          warmed[host] = 1
          write_request(config_file, request_key[request], "", request_host[request], 0)
        }
      }
      for (request = 1; request <= request_count; request++)
        write_request(config_file, request_key[request], request_range[request], request_host[request], 1)
      close(config_file)
      request_count = 0
    }
    function write_request(config_file, key, byte_range, host_index, measured) {
      if (config_file in has_request) printf "next\n" > config_file   # a trailing next would make curl run an empty transfer
      has_request[config_file] = 1
      if (mode == "blob")
        printf "url = \"%s/%s/%s?%s\"\n", blob_base, container, key, ENVIRON["SAS_QUERY"] > config_file
      else {
        printf "url = \"http://%s/%s/%s\"\n", host_list[host_index % host_count + 1], bucket, key > config_file
        printf "aws-sigv4 = \"aws:amz:us-east-1:s3\"\nuser = \"warp:benchmark\"\n" > config_file
      }
      if (!measured) printf "head\n" > config_file
      if (byte_range != "") printf "range = \"%s\"\n", byte_range > config_file
      # next resets the options, so every request carries its own.
      # retry-max-time stops new retries once a request has used its max-time (see the header).
      printf "connect-timeout = 10\nmax-time = %d\nretry = 3\nretry-all-errors\nretry-max-time = %d\n", ENVIRON["CURL_MAX_TIME"], ENVIRON["CURL_MAX_TIME"] > config_file
      # A warm-up HEAD writes no result line. The body goes to stdout, which the caller discards. With
      # output = "/dev/null", curl would truncate the output before a retry, fail on /dev/null and drop the
      # request without writing its result line.
      if (measured)
        printf "write-out = \"%%output{>>%s/results%d}%%{http_code} %%{time_starttransfer} %%{time_total} %%{size_download} %%{num_retries} %%{num_connects}\\n\"\n", work_dir, worker > config_file
    }' "$work_dir/keys"
done

# Killing curl at the deadline would cut off the requests in flight; instead each worker
# runs short batches (each its own curl run, warmed up as described in the header) and stops starting new
# ones once time is up.
start_seconds=$(cut -d" " -f1 /proc/uptime)
end_seconds=$(awk -v start="$start_seconds" -v duration="${DURATION_SECONDS:-0}" 'BEGIN { print start + duration }')
for worker in $(seq 1 "$CONCURRENCY"); do
  if [ "$KIND" = onepass ]; then
    if [ -f "$work_dir/config$worker" ]; then
      (curl -s -K "$work_dir/config$worker" > /dev/null 2>&1 || echo failed >> "$work_dir/curl_failures$worker") &
    fi
  else
    (
      batch_index=0
      while [ -f "$work_dir/config$worker.$batch_index" ] && awk -v end="$end_seconds" '{ exit !($1 < end) }' /proc/uptime; do
        curl -s -K "$work_dir/config$worker.$batch_index" > /dev/null 2>&1 || echo failed >> "$work_dir/curl_failures$worker"
        batch_index=$((batch_index + 1))
      done
      [ -f "$work_dir/config$worker.$batch_index" ] || echo exhausted > "$work_dir/exhausted$worker"
    ) &
  fi
done
wait
stop_seconds=$(cut -d" " -f1 /proc/uptime)

if ls "$work_dir"/exhausted* >/dev/null 2>&1; then
  fail "request budget exhausted before DURATION_SECONDS; raise MAX_REQUESTS_PER_WORKER (currently $MAX_REQUESTS_PER_WORKER)"
fi

touch "$work_dir/results0" "$work_dir/curl_failures0"
cat "$work_dir"/results* > "$work_dir/all_results"
awk -v status="$expected_status" -v size="$request_bytes" '$1 == status && $4 == size' "$work_dir/all_results" > "$work_dir/ok"
ok=$(wc -l < "$work_dir/ok")
http_errors=$(awk -v status="$expected_status" -v size="$request_bytes" '!($1 == status && $4 == size)' "$work_dir/all_results" | wc -l)
transport_errors=$(cat "$work_dir"/curl_failures* | wc -l)
err=$((http_errors + transport_errors))
retries=$(awk '{ sum += $5 } END { printf "%d", sum }' "$work_dir/all_results")
new_connections=$(awk '$6 > 0 { count++ } END { printf "%d", count }' "$work_dir/ok")
failures=$(awk -v status="$expected_status" -v size="$request_bytes" -v curl_exit="$transport_errors" '
  !($1 == status && $4 == size) { count[$1 " " $4]++ }
  END {
    if (curl_exit > 0) count["curl_exit"] = curl_exit
    printf "{"
    for (key in count) { printf "%s\"%s\":%d", separator, key, count[key]; separator = "," }
    printf "}"
  }' "$work_dir/all_results")

percentile_ms() {
  sort_column=$1
  fraction=$2
  awk -v column="$sort_column" '{ print $column }' "$work_dir/ok" | sort -n \
    | awk -v count="$ok" -v fraction="$fraction" 'NR == int(count * fraction) + 1 { printf "%.2f", $1 * 1000 }'
}
ttfb_p50=$(percentile_ms 2 0.50)
ttfb_p99=$(percentile_ms 2 0.99)
latency_p50=$(percentile_ms 3 0.50)
latency_p99=$(percentile_ms 3 0.99)

awk -v start="$start_seconds" -v stop="$stop_seconds" -v ok="$ok" -v err="$err" -v mode="$MODE" -v kind="$KIND" \
    -v concurrency="$CONCURRENCY" -v retries="$retries" -v failures="$failures" \
    -v new_connections="$new_connections" -v max_time="$CURL_MAX_TIME" \
    -v ttfb_p50="${ttfb_p50:-null}" -v ttfb_p99="${ttfb_p99:-null}" \
    -v latency_p50="${latency_p50:-null}" -v latency_p99="${latency_p99:-null}" \
  '{ bytes += $4 }
   END {
     wall = stop - start
     printf "{\"mode\":\"%s\",\"kind\":\"%s\",\"concurrency\":%d,\"ok\":%d,\"err\":%d,\"bytes\":%.0f,\"wall_seconds\":%.2f,", mode, kind, concurrency, ok, err, bytes, wall
     printf "\"retries\":%d,\"failures\":%s,\"new_connections\":%d,\"max_time_seconds\":%d,", retries, failures, new_connections, max_time
     printf "\"operations_per_second\":%.1f,\"mebibytes_per_second\":%.1f,", ok / wall, bytes / 1048576 / wall
     printf "\"ttfb_p50_ms\":%s,\"ttfb_p99_ms\":%s,\"latency_p50_ms\":%s,\"latency_p99_ms\":%s}\n", ttfb_p50, ttfb_p99, latency_p50, latency_p99
   }' "$work_dir/ok"

[ "$err" -eq 0 ] || fail "$err of $((ok + err)) requests did not return $expected_status with $request_bytes bytes; failures: $failures"
[ "$ok" -gt 0 ] || fail "no request succeeded"
