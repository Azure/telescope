def validate_dataset:
  [range(0; 16) | "object-" + (if . < 10 then "0" else "" end) + tostring + ".bin"] as $names
  | if type == "array" and length == 16
       and (map(.name) | sort) == $names
       and all(.[]; .properties.contentLength == 67108864)
    then .
    else error("Blob dataset must contain exactly 16 objects of 64 MiB (1 GiB total)")
    end;

def cache_counts:
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
      .value as $label
      | .value = ($report | capture("(?m)^\\s*" + $label + ":\\s*(?<count>[0-9]+)\\s*$").count | tonumber)
    )
  | if length == 6 and .total == 16 and .failed == 0
       and (.all + .one + .partial + .uncached) == .total
    then .
    else error("Cache report must cover exactly 16 files with consistent counts and no failures")
    end;

def positive_metric:
  type == "number" and isfinite and . > 0;

def warp_summary:
  if (.operations | type == "array" and length == 1) and .operations[0].type == "GET"
  then .operations[0]
  else error("Expected exactly one GET operation in Warp analysis")
  end
  | if .errors == 0 and .throughput.errors == 0 and .skipped == false
       and (.n | positive_metric) and (.throughput.ops | positive_metric)
       and .concurrency == 16 and .single_sized_requests.obj_size == 67108864
       and (.single_sized_requests.skipped // false) == false
       # Warp trims incomplete edge requests from its requested 60-second run.
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
