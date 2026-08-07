#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

if ! managed_telemetry_enabled; then
  echo "AKS control-plane managed Prometheus is disabled; skipping audit."
  exit 0
fi

: "${AUDIT_SCRIPT:?AUDIT_SCRIPT is required}"
: "${PLATFORM_EXPORT_SCRIPT:?PLATFORM_EXPORT_SCRIPT is required}"

initialize_managed_telemetry
load_collection_window

capacity_audit_ok=true
capacity_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
while IFS= read -r workspace; do
  workspace_slot=$(echo "$workspace" | jq -r '.slot // .name')
  workspace_id=$(echo "$workspace" | jq -r '.id')
  capacity_window_start=$(echo "$workspace" | jq -r \
    '.capacity_guard.monitoring_window_start // empty')
  if [ -z "$capacity_window_start" ]; then
    capacity_window_start="$configured_at"
  fi
  workspace_dir="$OUTPUT_DIR/workspace-${workspace_slot}"
  mkdir -p "$workspace_dir"
  capacity_raw="$workspace_dir/amw-capacity.json"
  capacity_summary="$workspace_dir/amw-capacity-summary.json"
  capacity_status=0
  if ! capture_amw_capacity \
      "$workspace_id" \
      "$capacity_window_start" \
      "$capacity_end" \
      "$capacity_raw" \
      "$capacity_summary"; then
    capacity_status=1
  else
    amw_capacity_runtime_ok "$capacity_summary" || capacity_status=$?
  fi
  if [ -s "$capacity_summary" ]; then
    write_amw_capacity_markdown \
      "$capacity_summary" \
      "$workspace_dir/amw-capacity-summary.md"
  fi
  if [ "$capacity_status" -ne 0 ]; then
    capacity_audit_ok=false
    echo "##vso[task.logissue type=error;] AMW capacity audit failed for workspace slot $workspace_slot."
  fi
done < <(echo "$workspaces_json" | jq -c '.[]')
echo "##vso[task.setvariable variable=AKS_AMW_CAPACITY_AUDITED]$capacity_audit_ok"

token=$(az account get-access-token \
  --resource https://prometheus.monitor.azure.com \
  --query accessToken -o tsv)
export PROMETHEUS_BEARER_TOKEN="$token"

# Bounds the ThreadPoolExecutor concurrency used for schema-v2 (one
# workspace per cluster) audits. Each cluster issues ~15 API calls
# (1 label-values + 1 /series per MANAGED_SERIES_METRICS entry), so at
# n100 scale serial execution can approach ~1500 calls and threaten the 3h
# finalization reserve. Higher worker counts trade wall-clock audit time
# against burstier concurrent load on the per-cluster query endpoints.
audit_workers="${AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS:-4}"
if ! [[ "$audit_workers" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_MANAGED_PROMETHEUS_AUDIT_WORKERS must be a positive integer." >&2
  exit 1
fi

set +e
python3 "$AUDIT_SCRIPT" managed \
  --endpoint "$endpoint" \
  --resource-scope "$resource_scope" \
  --manifest "$MANIFEST_PATH" \
  --start "$audit_start" \
  --end "$end_time" \
  --output-prefix "$OUTPUT_DIR/telemetry-audit-managed" \
  --workers "$audit_workers"
audit_rc=$?
set -e
unset PROMETHEUS_BEARER_TOKEN
if [ "$audit_rc" -ne 0 ]; then
  echo "##vso[task.logissue type=warning;] Managed Prometheus telemetry audit returned $audit_rc; inspect the published audit."
fi

while IFS= read -r cluster; do
  role=$(echo "$cluster" | jq -r '.role')
  cluster_id=$(echo "$cluster" | jq -r '.id')
  cluster_alias=$(echo "$cluster" | jq -r '.prometheus_cluster_alias')
  python3 "$PLATFORM_EXPORT_SCRIPT" \
    --resource "$cluster_id" \
    --cluster-label "$cluster_alias" \
    --start "$configured_at" \
    --end "$end_time" \
    --output "$OUTPUT_DIR/aks-platform-${role}.openmetrics" \
    --manifest "$OUTPUT_DIR/aks-platform-${role}.json"
done < <(jq -c '.clusters[]' "$MANIFEST_PATH")

echo "Managed telemetry audit and live-coupled platform metrics written to $OUTPUT_DIR"
if [ "$capacity_audit_ok" != "true" ]; then
  exit 1
fi
