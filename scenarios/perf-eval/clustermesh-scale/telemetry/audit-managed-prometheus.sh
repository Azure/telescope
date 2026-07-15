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
build_log_summary_query

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

echo "Managed telemetry audit, logs, and platform metrics written to $OUTPUT_DIR"
