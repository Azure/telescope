#!/usr/bin/env bash
set -euo pipefail

: "${MANIFEST_PATH:?MANIFEST_PATH is required}"
: "${OUTPUT_DIR:?OUTPUT_DIR is required}"
: "${RUN_ID:?RUN_ID is required}"

platform_metric_names_json='[
  "apiserver_cpu_usage_percentage",
  "apiserver_memory_usage_percentage",
  "etcd_cpu_usage_percentage",
  "etcd_memory_usage_percentage"
]'
timeout_seconds="${AKS_PLATFORM_METRICS_READINESS_TIMEOUT_SECONDS:-1800}"
poll_seconds="${AKS_PLATFORM_METRICS_READINESS_POLL_SECONDS:-60}"
lookback_seconds="${AKS_PLATFORM_METRICS_READINESS_LOOKBACK_SECONDS:-1800}"
minimum_samples="${AKS_PLATFORM_METRICS_READINESS_MIN_SAMPLES:-5}"
recent_grace_seconds="${AKS_PLATFORM_METRICS_READINESS_RECENT_GRACE_SECONDS:-300}"
query_timeout_seconds="${AKS_PLATFORM_METRICS_READINESS_QUERY_TIMEOUT_SECONDS:-120}"
output_file="$OUTPUT_DIR/platform-readiness.json"

for value_name in \
  timeout_seconds \
  poll_seconds \
  lookback_seconds \
  minimum_samples \
  recent_grace_seconds \
  query_timeout_seconds; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "${value_name} must be a non-negative integer." >&2
    exit 1
  fi
done
if [ "$minimum_samples" -lt 1 ]; then
  echo "minimum_samples must be at least 1." >&2
  exit 1
fi
if [ "$poll_seconds" -lt 1 ]; then
  echo "poll_seconds must be at least 1." >&2
  exit 1
fi
if [ "$query_timeout_seconds" -lt 1 ]; then
  echo "query_timeout_seconds must be at least 1." >&2
  exit 1
fi
if [ ! -s "$MANIFEST_PATH" ]; then
  echo "Managed telemetry manifest not found at $MANIFEST_PATH" >&2
  exit 1
fi
cluster_count=$(jq '.clusters | length' "$MANIFEST_PATH")
if [ "$cluster_count" -lt 1 ]; then
  echo "Managed telemetry manifest contains no clusters." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
cp "$MANIFEST_PATH" "$OUTPUT_DIR/run-manifest.json"
echo "##vso[task.setvariable variable=AKS_PLATFORM_METRICS_PRE_SCENARIO_READY]false"

current_time() {
  if [ -n "${AKS_PLATFORM_METRICS_READINESS_NOW:-}" ]; then
    printf '%s\n' "$AKS_PLATFORM_METRICS_READINESS_NOW"
  else
    date -u +%Y-%m-%dT%H:%M:%SZ
  fi
}

started_at=$(current_time)
started_epoch=$(date -u -d "$started_at" +%s)
deadline=$((started_epoch + timeout_seconds))
attempt=0
last_clusters='[]'

while true; do
  attempt=$((attempt + 1))
  observed_at=$(current_time)
  observed_epoch=$(date -u -d "$observed_at" +%s)
  query_start=$(date -u -d "@$((observed_epoch - lookback_seconds))" +%Y-%m-%dT%H:%M:%SZ)
  latest_required_epoch=$((observed_epoch - recent_grace_seconds))
  observations_file=$(mktemp)
  all_ready=true

  while IFS= read -r cluster; do
    role=$(jq -r '.role' <<<"$cluster")
    cluster_id=$(jq -r '.id' <<<"$cluster")
    response_file=$(mktemp)
    error_file=$(mktemp)
    query_rc=0
    timeout "${query_timeout_seconds}s" az monitor metrics list \
      --resource "$cluster_id" \
      --metrics \
        apiserver_cpu_usage_percentage \
        apiserver_memory_usage_percentage \
        etcd_cpu_usage_percentage \
        etcd_memory_usage_percentage \
      --interval PT1M \
      --aggregation Average \
      --start-time "$query_start" \
      --end-time "$observed_at" \
      -o json >"$response_file" 2>"$error_file" || query_rc=$?
    query_succeeded=true
    query_error=""
    if [ "$query_rc" -ne 0 ] || ! jq -e . "$response_file" >/dev/null 2>&1; then
      query_succeeded=false
      query_error=$(head -c 500 "$error_file" | tr '\n' ' ')
      if [ -z "$query_error" ]; then
        query_error="az monitor metrics list failed with exit code $query_rc"
      fi
      echo "##vso[task.logissue type=warning;] [$role] platform metric readiness query failed: $query_error"
      response='{"value":[]}'
    else
      response=$(cat "$response_file")
    fi
    rm -f "$response_file" "$error_file"
    metrics=$(jq -c \
      --argjson names "$platform_metric_names_json" \
      --argjson minimum_samples "$minimum_samples" \
      --argjson latest_required "$latest_required_epoch" '
        . as $response
        | [
            $names[] as $name
            | [
                $response.value[]?
                | select(.name.value == $name)
                | .timeseries[].data[]?
                | select(.average != null)
                | (
                    try (
                      .timeStamp
                      | .[0:19] + "Z"
                      | fromdateiso8601
                    )
                    catch empty
                  )
              ] as $timestamps
            | ($timestamps | unique) as $unique_timestamps
            | {
                name: $name,
                sample_count: ($unique_timestamps | length),
                first_epoch: ($unique_timestamps | min // null),
                last_epoch: ($unique_timestamps | max // null),
                ready: (
                  ($unique_timestamps | length) >= $minimum_samples
                  and ($unique_timestamps | max // 0) >= $latest_required
                )
              }
          ]' <<<"$response")
    ready_count=$(jq '[.[] | select(.ready == true)] | length' <<<"$metrics")
    cluster_ready=false
    if [ "$ready_count" -eq 4 ]; then
      cluster_ready=true
    else
      all_ready=false
    fi
    echo "[$role] platform readiness $ready_count/4 metrics; minimum_samples=$minimum_samples recent_grace=${recent_grace_seconds}s"
    jq -cn \
      --arg role "$role" \
      --arg cluster_id "$cluster_id" \
      --argjson ready "$cluster_ready" \
      --argjson query_succeeded "$query_succeeded" \
      --arg query_error "$query_error" \
      --argjson metrics "$metrics" \
      '{
        role: $role,
        cluster_id: $cluster_id,
        ready: $ready,
        query_succeeded: $query_succeeded,
        query_error: $query_error,
        metrics: $metrics
      }' >> "$observations_file"
  done < <(jq -c '.clusters[]' "$MANIFEST_PATH")

  last_clusters=$(jq -s '.' "$observations_file")
  rm -f "$observations_file"
  jq -n \
    --arg run_id "$RUN_ID" \
    --arg started_at "$started_at" \
    --arg observed_at "$observed_at" \
    --arg query_start "$query_start" \
    --argjson attempt "$attempt" \
    --argjson ready "$all_ready" \
    --argjson timeout_seconds "$timeout_seconds" \
    --argjson lookback_seconds "$lookback_seconds" \
    --argjson minimum_samples "$minimum_samples" \
    --argjson recent_grace_seconds "$recent_grace_seconds" \
    --argjson clusters "$last_clusters" \
    '{
      schema_version: 1,
      run_id: $run_id,
      started_at: $started_at,
      observed_at: $observed_at,
      query_start: $query_start,
      attempt: $attempt,
      ready: $ready,
      requirements: {
        timeout_seconds: $timeout_seconds,
        lookback_seconds: $lookback_seconds,
        minimum_samples_per_metric: $minimum_samples,
        recent_grace_seconds: $recent_grace_seconds
      },
      clusters: $clusters
    }' > "${output_file}.tmp"
  mv "${output_file}.tmp" "$output_file"

  if [ "$all_ready" = "true" ]; then
    echo "AKS platform CPU/memory metrics are streaming on every cluster."
    echo "##vso[task.setvariable variable=AKS_PLATFORM_METRICS_PRE_SCENARIO_READY]true"
    exit 0
  fi
  if [ "$observed_epoch" -ge "$deadline" ]; then
    break
  fi
  remaining=$((deadline - observed_epoch))
  sleep_for="$poll_seconds"
  if [ "$sleep_for" -gt "$remaining" ]; then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
done

echo "##vso[task.logissue type=error;] Required AKS platform CPU/memory metrics were not streaming before CL2; refusing to spend the scenario budget without full-window telemetry."
exit 1
