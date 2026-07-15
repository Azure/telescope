#!/usr/bin/env bash

managed_telemetry_enabled() {
  local enabled="${AKS_CONTROL_PLANE_METRICS_ENABLED:-false}"
  [ "${enabled,,}" = "true" ]
}

initialize_managed_telemetry() {
  : "${MANIFEST_PATH:?MANIFEST_PATH is required}"
  : "${OUTPUT_DIR:?OUTPUT_DIR is required}"
  : "${RUN_ID:?RUN_ID is required}"

  if [ ! -s "$MANIFEST_PATH" ]; then
    echo "Managed Prometheus run manifest not found at $MANIFEST_PATH" >&2
    return 1
  fi

  mkdir -p "$OUTPUT_DIR"
  collection_manifest="$OUTPUT_DIR/run-manifest.json"
  configured_at=$(jq -r '.configured_at' "$MANIFEST_PATH")
  endpoint=$(jq -r '.query.resource_endpoint' "$MANIFEST_PATH")
  resource_scope=$(jq -r '.query.resource_scope' "$MANIFEST_PATH")
  law_customer_id=$(jq -r '.logs.workspace.customer_id' "$MANIFEST_PATH")
  resource_ids_json=$(jq -c '[.clusters[].id]' "$MANIFEST_PATH")
}

load_collection_window() {
  if [ ! -s "$collection_manifest" ]; then
    echo "Managed telemetry collection window not found at $collection_manifest" >&2
    return 1
  fi

  end_time=$(jq -r '.collected_at' "$collection_manifest")
  audit_start=$(jq -r '.audit_window.start' "$collection_manifest")
}

build_log_summary_query() {
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
}
