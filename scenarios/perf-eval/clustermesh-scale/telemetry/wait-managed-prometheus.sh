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

platform_metric_names=(
  apiserver_cpu_usage_percentage
  apiserver_memory_usage_percentage
  etcd_cpu_usage_percentage
  etcd_memory_usage_percentage
)

wait_for_platform_metrics() {
  local timeout="${AKS_PLATFORM_METRICS_TIMEOUT_SECONDS:-3600}"
  local deadline=$(( $(date +%s) + timeout ))
  local missing role cluster_id available
  while [ "$(date +%s)" -lt "$deadline" ]; do
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

if ! wait_for_platform_metrics; then
  echo "##vso[task.logissue type=warning;] AKS platform CPU/memory metrics did not appear before timeout; exporting every available platform metric anyway."
fi

end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

if ! wait_for_logs; then
  echo "##vso[task.logissue type=warning;] AKS control-plane/audit logs did not appear before timeout; workspace remains authoritative and can be queried later."
fi
log_end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

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
jq \
  --arg collected_at "$end_time" \
  --arg audit_window_start "$audit_start" \
  --arg audit_window_end "$end_time" \
  --arg logs_window_end "$log_end_time" \
  '. + {
    collected_at: $collected_at,
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
echo "##vso[task.setvariable variable=AKS_TELEMETRY_WINDOW_READY]true"
