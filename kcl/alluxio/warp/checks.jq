def dataset_keys($count):
  [range($count) | "object-" + (if . < 10 then "0" else "" end) + tostring + ".bin"] | sort;

def validate_dataset($count; $object_size_bytes):
  if type == "array" and length == $count
       and (map(.name) | sort) == dataset_keys($count)
       and all(.[]; .properties.contentLength == $object_size_bytes)
    then .
    else error("Blob dataset must contain exactly \($count) objects of \($object_size_bytes) bytes each")
    end;

def cache_counts($count):
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
  | if length == 6 and .total == $count and .failed == 0
       and (.all + .one + .partial + .uncached) == .total
    then .
    else error("Cache report must cover exactly \($count) files with consistent counts and no failures")
    end;

def positive_metric:
  type == "number" and isfinite and . > 0;

def cold_warp_summary($count; $object_size_bytes):
  # The cold clients use UTC. Warp timestamps can have a variable-length fractional second.
  def seconds:
    (capture("^(?<whole>[^.Z]+)(?<fraction>\\.[0-9]+)?Z$") // error("Expected UTC Warp timestamp"))
    | ((.whole + "Z" | fromdateiso8601) + ("0" + (.fraction // "") | tonumber));
  split("\n") | map(select(length > 0 and (startswith("#") | not)) | split("\t"))
  | .[0] as $header | .[1:] | map([$header, .] | transpose | map({(.[0]): .[1]}) | add)
  | if (map(.file) | sort) != dataset_keys($count) or
       any(.[]; .op != "GET" or .error != "" or .bytes != ($object_size_bytes | tostring) or .n_objects != "1" or
                (.duration_ns | tonumber) <= 0)
    then error("Cold Warp run must record exactly one successful GET of \($object_size_bytes) bytes per dataset key") else . end
  # Use the observed transfer interval, not the configured window or the sum of overlapping GET times.
  | (min_by(.start | seconds).start) as $start | (max_by(.end | seconds).end) as $finish
  | (($finish | seconds) - ($start | seconds)) as $elapsed
  | if ($elapsed | positive_metric) then . else error("Invalid cold Warp measurement interval") end
  | (map(.duration_ns | tonumber / 1000000) | sort) as $latencies
  | {
      phase: "cold-start", concurrency: length, objects_read: length, errors: 0,
      dataset_bytes: (map(.bytes | tonumber) | add),
      elapsed_seconds: $elapsed, measurement_start: $start, measurement_end: $finish,
      operations_per_second: (length / $elapsed),
      latency_avg_ms: ($latencies | add / length),
      latency_p50_ms: (($latencies[(($count - 1) / 2 | floor)] + $latencies[($count / 2 | floor)]) / 2),
      latency_p99_ms: $latencies[(($count * 0.99 | ceil) - 1)]
    } | .bytes_per_second = (.dataset_bytes / $elapsed);

def warp_summary($count; $object_size_bytes):
  if (.operations | type == "array" and length == 1) and .operations[0].type == "GET"
  then .operations[0]
  else error("Expected exactly one GET operation in Warp analysis")
  end
  | if .errors == 0 and .throughput.errors == 0 and .skipped == false
       and (.n | positive_metric) and (.throughput.ops | positive_metric)
       and .concurrency == $count and .single_sized_requests.obj_size == $object_size_bytes
       and (.single_sized_requests.skipped // false) == false
       # Checks the run is about 60s, trimming incomplete requests.
       and .throughput.measure_duration_millis >= 54000
       and .throughput.measure_duration_millis <= 66000
    then {
      bytes_per_second: (.throughput.bytes * 1000 / .throughput.measure_duration_millis),
      operations_per_second: (.throughput.ops * 1000 / .throughput.measure_duration_millis),
      latency_avg_ms: .single_sized_requests.dur_avg_millis,
      latency_p50_ms: .single_sized_requests.dur_median_millis,
      latency_p99_ms: .single_sized_requests.dur_99_millis,
      errors: .errors,
      measurement_start: .throughput.start_time,
      measurement_end: .throughput.end_time
    }
    else error("Warp reported errors, incomplete analysis, or an unexpected workload shape")
    end
  | if ([.bytes_per_second, .operations_per_second, .latency_avg_ms, .latency_p50_ms, .latency_p99_ms]
        | all(.[]; positive_metric))
    then .
    else error("Warp produced invalid throughput or latency metrics")
    end;
