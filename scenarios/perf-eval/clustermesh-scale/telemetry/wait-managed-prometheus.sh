#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

if ! managed_telemetry_enabled; then
  echo "AKS control-plane managed Prometheus is disabled; skipping ingestion wait."
  exit 0
fi

initialize_managed_telemetry

capacity_raw="$OUTPUT_DIR/amw-capacity.json"
capacity_summary="$OUTPUT_DIR/amw-capacity-summary.json"
managed_prometheus_throttled=false
amw_capacity_verified=false

refresh_amw_capacity() {
  local capacity_end
  capacity_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  capture_amw_capacity \
    "$amw_id" \
    "$capacity_window_start" \
    "$capacity_end" \
    "$capacity_raw" \
    "$capacity_summary"
}

check_runtime_amw_capacity() {
  local runtime_rc=0
  if ! refresh_amw_capacity; then
    echo "##vso[task.logissue type=warning;] Unable to refresh AMW capacity metrics."
    return 1
  fi
  amw_capacity_runtime_ok "$capacity_summary" || runtime_rc=$?
  if [ "$runtime_rc" -eq 1 ]; then
    amw_capacity_verified=false
    return 1
  fi
  amw_capacity_verified=true
  return "$runtime_rc"
}

platform_metric_names=(
  apiserver_cpu_usage_percentage
  apiserver_memory_usage_percentage
  etcd_cpu_usage_percentage
  etcd_memory_usage_percentage
)

wait_for_platform_metrics() {
  local timeout="${AKS_PLATFORM_METRICS_TIMEOUT_SECONDS:-3600}"
  local deadline=$(( $(date +%s) + timeout ))
  local missing role cluster_id available capacity_rc
  while [ "$(date +%s)" -lt "$deadline" ]; do
    capacity_rc=0
    check_runtime_amw_capacity || capacity_rc=$?
    if [ "$capacity_rc" -eq 2 ]; then
      return 2
    fi
    missing=0
    while IFS= read -r cluster; do
      role=$(echo "$cluster" | jq -r '.role')
      cluster_id=$(echo "$cluster" | jq -r '.id')
      available=$(az monitor metrics list \
        --resource "$cluster_id" \
        --metrics "${platform_metric_names[@]}" \
        --interval PT1M \
        --aggregation Average \
        --start-time "$configured_at" \
        --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        -o json 2>/dev/null \
        | jq '[.value[] | select(any(.timeseries[].data[]?; .average != null))] | length' \
        || echo 0)
      if [ "${available:-0}" -ne "${#platform_metric_names[@]}" ]; then
        echo "[$role] waiting for platform CPU/memory metrics ($available/${#platform_metric_names[@]})"
        missing=$((missing + 1))
      fi
    done < <(jq -c '.clusters[]' "$MANIFEST_PATH")
    if [ "$missing" -eq 0 ]; then
      return 0
    fi
    sleep 60
  done
  return 1
}

platform_wait_rc=0
wait_for_platform_metrics || platform_wait_rc=$?
if [ "$platform_wait_rc" -eq 2 ]; then
  managed_prometheus_throttled=true
  echo "##vso[task.logissue type=error;] AMW throttling started while waiting for AKS platform metrics."
elif [ "$platform_wait_rc" -ne 0 ]; then
  echo "##vso[task.logissue type=warning;] AKS platform CPU/memory metrics did not appear before timeout; exporting every available platform metric anyway."
fi
end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

wait_for_managed_prometheus() {
  local timeout="${AKS_MANAGED_PROMETHEUS_TIMEOUT_SECONDS:-3600}"
  local poll_seconds="${AKS_MANAGED_PROMETHEUS_POLL_SECONDS:-60}"
  local deadline=$(( $(date +%s) + timeout ))
  local expected_clusters expected_count expected_regex
  local remaining command_timeout sleep_seconds token response available query
  local capacity_rc
  expected_clusters=$(jq -c '[.clusters[].prometheus_cluster_alias]' "$MANIFEST_PATH")
  expected_count=$(echo "$expected_clusters" | jq 'length')
  expected_regex=$(echo "$expected_clusters" | jq -r 'join("|")')
  query="count by(cluster)(apiserver_request_total{cluster=~\"$expected_regex\"})"

  while [ "$(date +%s)" -lt "$deadline" ]; do
    capacity_rc=0
    check_runtime_amw_capacity || capacity_rc=$?
    if [ "$capacity_rc" -eq 2 ]; then
      return 2
    fi
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    command_timeout=$remaining
    if [ "$command_timeout" -gt 120 ]; then
      command_timeout=120
    fi
    token=$(timeout "${command_timeout}s" az account get-access-token \
      --resource https://prometheus.monitor.azure.com \
      --query accessToken -o tsv 2>/dev/null || true)
    if [ -n "$token" ]; then
      remaining=$((deadline - $(date +%s)))
      if [ "$remaining" -le 0 ]; then
        break
      fi
      command_timeout=$remaining
      if [ "$command_timeout" -gt 120 ]; then
        command_timeout=120
      fi
      response=$(curl -fsS -G "$endpoint/api/v1/query_range" \
        --connect-timeout 10 \
        --max-time "$command_timeout" \
        -H "Authorization: Bearer $token" \
        -H "x-ms-azure-scoping: $resource_scope" \
        --data-urlencode "query=$query" \
        --data-urlencode "start=$configured_at" \
        --data-urlencode "end=$end_time" \
        --data-urlencode "step=60s" \
        2>/dev/null || true)
      if [ -z "$response" ]; then
        response='{}'
      fi
      available=$(printf '%s' "$response" | jq \
        --argjson expected "$expected_clusters" \
        '[
          .data.result[]?
          | select((.values // []) | length > 0)
          | .metric.cluster
          | select(. as $cluster | $expected | index($cluster))
        ] | unique | length' 2>/dev/null || echo 0)
      if [ "${available:-0}" -eq "$expected_count" ]; then
        echo "Managed Prometheus samples are available for all $expected_count clusters."
        return 0
      fi
    else
      available=0
    fi
    echo "Waiting for managed Prometheus samples ($available/$expected_count clusters)..."
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    sleep_seconds=$poll_seconds
    if [ "$sleep_seconds" -gt "$remaining" ]; then
      sleep_seconds=$remaining
    fi
    if [ "$sleep_seconds" -gt 0 ]; then
      sleep "$sleep_seconds"
    fi
  done
  return 1
}

managed_prometheus_ready=false
managed_wait_rc=1
if [ "$managed_prometheus_throttled" = "true" ]; then
  managed_wait_rc=2
else
  managed_wait_rc=0
  wait_for_managed_prometheus || managed_wait_rc=$?
fi
if [ "$managed_wait_rc" -eq 0 ]; then
  managed_prometheus_ready=true
elif [ "$managed_wait_rc" -eq 2 ]; then
  if [ "$managed_prometheus_throttled" != "true" ]; then
    echo "##vso[task.logissue type=error;] AMW throttling started before run-scoped Prometheus samples became queryable."
  fi
  managed_prometheus_throttled=true
else
  echo "##vso[task.logissue type=warning;] Managed Prometheus samples did not appear before timeout; audit/log/platform artifacts will be preserved, but zero-data TSDB reconstruction will be skipped."
fi

log_end_time="$end_time"
build_log_summary_query

wait_for_logs() {
  local timeout="${AKS_CONTROL_PLANE_LOGS_TIMEOUT_SECONDS:-1800}"
  local deadline=$(( $(date +%s) + timeout ))
  local count
  while [ "$(date +%s)" -lt "$deadline" ]; do
    log_end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    build_log_summary_query
    count=$(az monitor log-analytics query \
      --workspace "$law_customer_id" \
      --analytics-query "$log_summary_query" \
      --query 'length(@)' \
      -o tsv 2>/dev/null || echo 0)
    if [ "${count:-0}" -gt 0 ]; then
      return 0
    fi
    echo "Waiting for AKS control-plane/audit log ingestion..."
    sleep 60
  done
  return 1
}

logs_wait_rc=0
wait_for_logs || logs_wait_rc=$?
if [ "$logs_wait_rc" -ne 0 ]; then
  echo "##vso[task.logissue type=warning;] AKS control-plane/audit logs did not appear before timeout; workspace remains authoritative and can be queried later."
fi
log_end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

final_capacity_rc=0
check_runtime_amw_capacity || final_capacity_rc=$?
if [ "$final_capacity_rc" -eq 2 ]; then
  managed_prometheus_throttled=true
  managed_prometheus_ready=false
elif [ "$final_capacity_rc" -ne 0 ]; then
  amw_capacity_verified=false
  managed_prometheus_ready=false
  echo "##vso[task.logissue type=warning;] Final AMW capacity could not be verified; TSDB reconstruction will be skipped."
fi
if [ -s "$capacity_summary" ]; then
  write_amw_capacity_markdown \
    "$capacity_summary" \
    "$OUTPUT_DIR/amw-capacity-summary.md"
fi

start_epoch=$(date -u -d "$configured_at" +%s)
end_epoch=$(date -u -d "$end_time" +%s)
max_series_window_seconds=$((12 * 60 * 60 - 60))
if [ $((end_epoch - start_epoch)) -gt "$max_series_window_seconds" ]; then
  audit_start_epoch=$((end_epoch - max_series_window_seconds))
  audit_start=$(date -u -d "@$audit_start_epoch" +%Y-%m-%dT%H:%M:%SZ)
else
  audit_start="$configured_at"
fi

collection_manifest_tmp="${collection_manifest}.tmp"
capacity_summary_json='{}'
if [ -s "$capacity_summary" ]; then
  capacity_summary_json=$(cat "$capacity_summary")
fi
jq \
  --arg collected_at "$end_time" \
  --arg audit_window_start "$audit_start" \
  --arg audit_window_end "$end_time" \
  --arg logs_window_end "$log_end_time" \
  --argjson managed_prometheus_ready "$managed_prometheus_ready" \
  --argjson managed_prometheus_throttled "$managed_prometheus_throttled" \
  --argjson amw_capacity_verified "$amw_capacity_verified" \
  --argjson amw_capacity "$capacity_summary_json" \
  '. + {
    collected_at: $collected_at,
    managed_prometheus_ready: $managed_prometheus_ready,
    managed_prometheus_throttled: $managed_prometheus_throttled,
    amw_capacity_verified: $amw_capacity_verified,
    amw_capacity: $amw_capacity,
    audit_window: {
      start: $audit_window_start,
      end: $audit_window_end
    },
    logs_window: {
      start: .configured_at,
      end: $logs_window_end
    }
  }' "$MANIFEST_PATH" > "$collection_manifest_tmp"
mv "$collection_manifest_tmp" "$collection_manifest"

echo "Managed telemetry collection window: $audit_start .. $end_time"
echo "Managed telemetry log window: $configured_at .. $log_end_time"
amw_capacity_ok=false
if [ "$managed_prometheus_throttled" = "false" ] &&
   [ "$amw_capacity_verified" = "true" ]; then
  amw_capacity_ok=true
fi
echo "##vso[task.setvariable variable=AKS_TELEMETRY_WINDOW_READY]true"
echo "##vso[task.setvariable variable=AKS_MANAGED_PROMETHEUS_READY]$managed_prometheus_ready"
echo "##vso[task.setvariable variable=AKS_AMW_CAPACITY_OK]$amw_capacity_ok"
