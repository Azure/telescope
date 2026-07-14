#!/usr/bin/env bash
set -euo pipefail

enabled="${AKS_CONTROL_PLANE_METRICS_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  echo "AKS control-plane managed Prometheus is disabled; skipping collection."
  exit 0
fi

: "${MANIFEST_PATH:?MANIFEST_PATH is required}"
: "${AUDIT_SCRIPT:?AUDIT_SCRIPT is required}"
: "${TSDB_EXPORT_SCRIPT:?TSDB_EXPORT_SCRIPT is required}"
: "${PLATFORM_EXPORT_SCRIPT:?PLATFORM_EXPORT_SCRIPT is required}"
: "${OUTPUT_DIR:?OUTPUT_DIR is required}"
: "${RUN_ID:?RUN_ID is required}"

if [ ! -s "$MANIFEST_PATH" ]; then
  echo "Managed Prometheus run manifest not found at $MANIFEST_PATH" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
configured_at=$(jq -r '.configured_at' "$MANIFEST_PATH")
endpoint=$(jq -r '.query.resource_endpoint' "$MANIFEST_PATH")
resource_scope=$(jq -r '.query.resource_scope' "$MANIFEST_PATH")
law_customer_id=$(jq -r '.logs.workspace.customer_id' "$MANIFEST_PATH")
resource_ids_json=$(jq -c '[.clusters[].id]' "$MANIFEST_PATH")

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

log_summary_query=$(cat <<EOF
let ResourceIds=dynamic(${resource_ids_json});
union withsource=TableName isfuzzy=true
  AKSControlPlane,
  AKSAudit,
  AKSAuditAdmin
| where TimeGenerated between (datetime(${configured_at}) .. datetime(${end_time}))
| where _ResourceId in~ (ResourceIds)
| summarize Count=count(), First=min(TimeGenerated), Last=max(TimeGenerated)
  by TableName, Category=tostring(column_ifexists("Category", ""))
| order by TableName asc, Category asc
EOF
)

wait_for_logs() {
  local timeout="${AKS_CONTROL_PLANE_LOGS_TIMEOUT_SECONDS:-1800}"
  local deadline=$(( $(date +%s) + timeout ))
  local count
  while [ "$(date +%s)" -lt "$deadline" ]; do
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

az monitor log-analytics query \
  --workspace "$law_customer_id" \
  --analytics-query "$log_summary_query" \
  -o json > "$OUTPUT_DIR/control-plane-log-summary.json" || true

while IFS= read -r cluster; do
  role=$(echo "$cluster" | jq -r '.role')
  cluster_id=$(echo "$cluster" | jq -r '.id')
  log_sample_query=$(cat <<EOF
union withsource=TableName isfuzzy=true
  AKSControlPlane,
  AKSAudit,
  AKSAuditAdmin
| where TimeGenerated between (datetime(${configured_at}) .. datetime(${end_time}))
| where _ResourceId =~ "${cluster_id}"
| extend CategoryValue=tostring(column_ifexists("Category", ""))
| project
    TableName,
    TimeGenerated,
    Category=CategoryValue,
    Record=pack_all()
| top ${AKS_CONTROL_PLANE_LOG_SAMPLE_ROWS:-5000} by TimeGenerated desc
EOF
)
  az monitor log-analytics query \
    --workspace "$law_customer_id" \
    --analytics-query "$log_sample_query" \
    -o json > "$OUTPUT_DIR/control-plane-log-sample-${role}.json" || true
done < <(jq -c '.clusters[]' "$MANIFEST_PATH")

start_epoch=$(date -u -d "$configured_at" +%s)
end_epoch=$(date -u -d "$end_time" +%s)
max_series_window_seconds=$((12 * 60 * 60 - 60))
if [ $((end_epoch - start_epoch)) -gt "$max_series_window_seconds" ]; then
  audit_start_epoch=$((end_epoch - max_series_window_seconds))
  audit_start=$(date -u -d "@$audit_start_epoch" +%Y-%m-%dT%H:%M:%SZ)
else
  audit_start="$configured_at"
fi

token=$(az account get-access-token \
  --resource https://prometheus.monitor.azure.com \
  --query accessToken -o tsv)
export PROMETHEUS_BEARER_TOKEN="$token"

set +e
python3 "$AUDIT_SCRIPT" managed \
  --endpoint "$endpoint" \
  --resource-scope "$resource_scope" \
  --manifest "$MANIFEST_PATH" \
  --start "$audit_start" \
  --end "$end_time" \
  --output-prefix "$OUTPUT_DIR/telemetry-audit-managed"
audit_rc=$?
set -e
if [ "$audit_rc" -ne 0 ]; then
  echo "##vso[task.logissue type=warning;] Managed Prometheus telemetry audit returned $audit_rc; inspect the published audit."
fi

extra_openmetrics_args=()
while IFS= read -r cluster; do
  role=$(echo "$cluster" | jq -r '.role')
  cluster_id=$(echo "$cluster" | jq -r '.id')
  cluster_alias=$(echo "$cluster" | jq -r '.prometheus_cluster_alias')
  platform_metrics="$OUTPUT_DIR/aks-platform-${role}.openmetrics"
  platform_manifest="$OUTPUT_DIR/aks-platform-${role}.json"
  python3 "$PLATFORM_EXPORT_SCRIPT" \
    --resource "$cluster_id" \
    --cluster-label "$cluster_alias" \
    --start "$configured_at" \
    --end "$end_time" \
    --output "$platform_metrics" \
    --manifest "$platform_manifest"
  extra_openmetrics_args+=(--extra-openmetrics "$platform_metrics")
done < <(jq -c '.clusters[]' "$MANIFEST_PATH")

prometheus_version="${AMW_PROMETHEUS_VERSION:-3.13.0}"
promtool_dir="$OUTPUT_DIR/promtool-${prometheus_version}"
promtool="$promtool_dir/promtool"
if [ ! -x "$promtool" ]; then
  mkdir -p "$promtool_dir"
  archive="$OUTPUT_DIR/prometheus-${prometheus_version}.tar.gz"
  curl -fsSL \
    "https://github.com/prometheus/prometheus/releases/download/v${prometheus_version}/prometheus-${prometheus_version}.linux-amd64.tar.gz" \
    -o "$archive"
  tar xzf "$archive" \
    --strip-components=1 \
    -C "$promtool_dir" \
    "prometheus-${prometheus_version}.linux-amd64/promtool"
  rm -f "$archive"
fi

python3 "$TSDB_EXPORT_SCRIPT" \
  --endpoint "$endpoint" \
  --resource-scope "$resource_scope" \
  --start "$configured_at" \
  --end "$end_time" \
  --step-seconds "${AKS_MANAGED_TSDB_STEP_SECONDS:-15}" \
  --chunk-seconds "${AKS_MANAGED_TSDB_CHUNK_SECONDS:-1800}" \
  --workers "${AKS_MANAGED_TSDB_WORKERS:-8}" \
  --metrics-per-block "${AKS_MANAGED_TSDB_METRICS_PER_BLOCK:-25}" \
  --promtool "$promtool" \
  "${extra_openmetrics_args[@]}" \
  --output-dir "$OUTPUT_DIR"

unset PROMETHEUS_BEARER_TOKEN

if [ -f "$OUTPUT_DIR/data/amw-export-manifest.json" ]; then
  cp "$OUTPUT_DIR/data/amw-export-manifest.json" \
    "$OUTPUT_DIR/amw-export-manifest.json"
  rm -rf "$OUTPUT_DIR/data"
fi
rm -rf "$promtool_dir"

jq \
  --arg collected_at "$end_time" \
  --arg audit_window_start "$audit_start" \
  --arg audit_window_end "$end_time" \
  '. + {
    collected_at: $collected_at,
    audit_window: {
      start: $audit_window_start,
      end: $audit_window_end
    }
  }' "$MANIFEST_PATH" > "$OUTPUT_DIR/run-manifest.json"

storage_account="${CL2_PROM_SNAPSHOT_STORAGE_ACCOUNT:-cmshscaleprom}"
container="${CL2_PROM_SNAPSHOT_CONTAINER:-snapshots}"
build_branch="${BUILD_BRANCH:-unknown-branch}"
for file in "$OUTPUT_DIR"/*; do
  [ -f "$file" ] || continue
  blob_name="${build_branch}/managed-control-plane/${RUN_ID}/$(basename "$file")"
  echo "Uploading $file -> $storage_account/$container/$blob_name"
  az storage blob upload \
    --account-name "$storage_account" \
    --container-name "$container" \
    --name "$blob_name" \
    --file "$file" \
    --auth-mode login \
    --overwrite \
    --output none
done

echo "Managed Prometheus audit, platform metrics, and reconstructed TSDB written to $OUTPUT_DIR"
