#!/usr/bin/env bash

managed_telemetry_enabled() {
  local enabled="${AKS_CONTROL_PLANE_METRICS_ENABLED:-false}"
  [ "${enabled,,}" = "true" ]
}

ensure_azure_provider_registered() {
  local namespace="${1:?Azure resource provider namespace is required}"
  local force_registration="${2:-false}"
  local timeout="${AKS_PROVIDER_REGISTRATION_TIMEOUT_SECONDS:-1800}"
  local poll_seconds="${AKS_PROVIDER_REGISTRATION_POLL_SECONDS:-15}"
  local deadline=$(( $(date +%s) + timeout ))
  local registration_requested=false
  local state=""
  local error_file

  while [ "$(date +%s)" -lt "$deadline" ]; do
    error_file=$(mktemp)
    if state=$(az provider show \
        --namespace "$namespace" \
        --query registrationState \
        -o tsv 2>"$error_file"); then
      rm -f "$error_file"
      if [ "$state" = "Registered" ] && {
        [ "${force_registration,,}" != "true" ] ||
          [ "$registration_requested" = "true" ]
      }; then
        echo "Resource provider $namespace is registered."
        return 0
      fi
    else
      echo "##vso[task.logissue type=warning;] Unable to query resource provider $namespace: $(tr '\n' ' ' < "$error_file")"
      rm -f "$error_file"
      state=""
    fi

    if [ "${force_registration,,}" = "true" ] &&
       [ "$registration_requested" != "true" ]; then
      echo "Forcing resource provider re-registration for $namespace..."
      if az provider register \
          --namespace "$namespace" \
          --output none; then
        registration_requested=true
      else
        echo "##vso[task.logissue type=warning;] Forced resource provider registration request for $namespace failed; retrying."
      fi
    elif [ "$state" != "Registering" ]; then
      echo "Requesting resource provider registration for $namespace..."
      if ! az provider register \
          --namespace "$namespace" \
          --output none; then
        echo "##vso[task.logissue type=warning;] Resource provider registration request for $namespace failed; polling and retrying."
      fi
    else
      echo "Resource provider $namespace is Registering."
    fi
    sleep "$poll_seconds"
  done

  echo "Timed out waiting for resource provider $namespace registration." >&2
  return 1
}

snapshot_label_value() {
  printf '%s' "$1" \
    | sed -E 's/[^a-zA-Z0-9_.:-]+/_/g; s/^_+//; s/_+$//'
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
