#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=managed-prometheus-common.sh
source "$script_dir/managed-prometheus-common.sh"

enabled="${AKS_CONTROL_PLANE_METRICS_ENABLED:-false}"
if [ "${enabled,,}" != "true" ]; then
  echo "AKS control-plane managed Prometheus is disabled; skipping configuration."
  exit 0
fi

: "${RUN_ID:?RUN_ID is required}"
: "${REGION:?REGION is required}"
: "${CONFIGMAP_PATH:?CONFIGMAP_PATH is required}"
: "${CONTROL_PLANE_MONITORS_PATH:?CONTROL_PLANE_MONITORS_PATH is required}"
: "${MANIFEST_PATH:?MANIFEST_PATH is required}"
CLUSTERS_FILE="${CLUSTERS_FILE:-$HOME/.kube/clustermesh-clusters.json}"
mkdir -p "$(dirname "$MANIFEST_PATH")"

if [ ! -s "$CLUSTERS_FILE" ]; then
  echo "Cluster inventory not found at $CLUSTERS_FILE" >&2
  exit 1
fi
if [ ! -f "$CONFIGMAP_PATH" ]; then
  echo "AMA metrics configmap not found at $CONFIGMAP_PATH" >&2
  exit 1
fi
if [ ! -f "$CONTROL_PLANE_MONITORS_PATH" ]; then
  echo "Managed Prometheus control-plane monitor not found at $CONTROL_PLANE_MONITORS_PATH" >&2
  exit 1
fi

register_preview="${AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW:-false}"
force_container_service_reregistration=false
if [ "${register_preview,,}" = "true" ]; then
  force_container_service_reregistration=true
fi
feature_name="AzureMonitorMetricsControlPlanePreview"
feature_state=$(az feature show \
  --namespace Microsoft.ContainerService \
  --name "$feature_name" \
  --query properties.state -o tsv 2>/dev/null || true)
if [ "$feature_state" != "Registered" ]; then
  if [ "${register_preview,,}" != "true" ]; then
    echo "AKS control-plane metrics preview is $feature_state, not Registered." >&2
    echo "Register it once with:" >&2
    echo "  az feature register --namespace Microsoft.ContainerService --name $feature_name" >&2
    echo "Then re-register Microsoft.ContainerService, or set" >&2
    echo "AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW=true for the canary stage." >&2
    exit 1
  fi

  echo "Registering AKS control-plane metrics preview feature..."
  az feature register \
    --namespace Microsoft.ContainerService \
    --name "$feature_name" \
    --output none
  deadline=$(( $(date +%s) + ${AKS_CONTROL_PLANE_FEATURE_TIMEOUT_SECONDS:-3600} ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    feature_state=$(az feature show \
      --namespace Microsoft.ContainerService \
      --name "$feature_name" \
      --query properties.state -o tsv 2>/dev/null || true)
    if [ "$feature_state" = "Registered" ]; then
      break
    fi
    echo "Preview feature state=$feature_state; waiting 30s..."
    sleep 30
  done
  if [ "$feature_state" != "Registered" ]; then
    echo "Timed out waiting for $feature_name registration." >&2
    exit 1
  fi
fi

for namespace in \
  Microsoft.ContainerService \
  Microsoft.Monitor \
  Microsoft.Insights \
  Microsoft.AlertsManagement \
  Microsoft.OperationalInsights; do
  echo "Ensuring resource provider $namespace is registered..."
  if [ "$namespace" = "Microsoft.ContainerService" ] &&
     [ "$force_container_service_reregistration" = "true" ]; then
    ensure_azure_provider_registered "$namespace" true
  else
    ensure_azure_provider_registered "$namespace"
  fi
done

subscription_id=$(az account show --query id -o tsv)
amw_resource_group="${AKS_CONTROL_PLANE_AMW_RESOURCE_GROUP:-clustermesh-scale-prom-snapshots}"
amw_name_prefix="${AKS_CONTROL_PLANE_AMW_NAME_PREFIX:-cmsh-scale-${REGION}-amw}"
legacy_amw_name="${AKS_CONTROL_PLANE_AMW_NAME:-}"
law_name="${AKS_CONTROL_PLANE_LAW_NAME:-cmsh-scale-controlplane-law}"
law_location="${AKS_CONTROL_PLANE_LAW_LOCATION:-eastus2}"
diagnostic_setting_name="${AKS_CONTROL_PLANE_DIAGNOSTIC_SETTING_NAME:-clustermesh-scale-full-telemetry}"
amw_arm_batch_size="${AKS_AMW_ARM_BATCH_SIZE:-10}"
preflight_window_minutes="${AKS_AMW_PREFLIGHT_WINDOW_MINUTES:-15}"
preflight_threshold="${AKS_AMW_PREFLIGHT_MAX_UTILIZATION_PERCENT:-40}"

if ! [[ "$amw_arm_batch_size" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_ARM_BATCH_SIZE must be a positive integer." >&2
  exit 1
fi
if ! [[ "$preflight_window_minutes" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_PREFLIGHT_WINDOW_MINUTES must be a positive integer." >&2
  exit 1
fi

mapfile -t source_cluster_rows < <(jq -c '.[]' "$CLUSTERS_FILE")
if [ "${#source_cluster_rows[@]}" -eq 0 ]; then
  echo "No clusters found in $CLUSTERS_FILE" >&2
  exit 1
fi
if [ -n "$legacy_amw_name" ] &&
   [ "${#source_cluster_rows[@]}" -gt 1 ]; then
  echo "AKS_CONTROL_PLANE_AMW_NAME cannot be used for a multi-cluster run; use AKS_CONTROL_PLANE_AMW_NAME_PREFIX so every cluster receives its own workspace." >&2
  exit 1
fi

if ! az group show --name "$amw_resource_group" --output none 2>/dev/null; then
  echo "Creating persistent telemetry resource group $amw_resource_group..."
  az group create \
    --name "$amw_resource_group" \
    --location "$REGION" \
    --tags scenario=clustermesh-scale telemetry=managed-prometheus \
    --output none
fi

workspace_spec_jsonl=$(mktemp)
for row in "${source_cluster_rows[@]}"; do
  role=$(echo "$row" | jq -r '.role')
  slot=$(printf '%s' "$role" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')
  if [ -n "$legacy_amw_name" ]; then
    workspace_name="$legacy_amw_name"
    slot="shared"
  else
    workspace_name="${amw_name_prefix}-${slot}"
  fi
  if [ "${#workspace_name}" -gt 63 ]; then
    echo "Azure Monitor workspace name exceeds 63 characters: $workspace_name" >&2
    exit 1
  fi
  jq -cn \
    --arg role "$role" \
    --arg slot "$slot" \
    --arg name "$workspace_name" \
    '{role: $role, slot: $slot, name: $name}' \
    >> "$workspace_spec_jsonl"
done
workspace_assignments=$(jq -s '.' "$workspace_spec_jsonl")
workspace_specs=$(echo "$workspace_assignments" | jq 'unique_by(.name)')
rm -f "$workspace_spec_jsonl"

mapfile -t missing_workspace_names < <(
  echo "$workspace_specs" | jq -r '.[].name' | while IFS= read -r workspace_name; do
    if ! az monitor account show \
        --resource-group "$amw_resource_group" \
        --name "$workspace_name" \
        --output none 2>/dev/null; then
      printf '%s\n' "$workspace_name"
    fi
  done
)

deployment_prefix=$(printf 'cmsh-amw-%s' "$RUN_ID" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')
for ((batch_start = 0; batch_start < ${#missing_workspace_names[@]}; batch_start += amw_arm_batch_size)); do
  batch_names=("${missing_workspace_names[@]:batch_start:amw_arm_batch_size}")
  batch_json=$(printf '%s\n' "${batch_names[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))')
  arm_template=$(mktemp)
  jq -n \
    --arg location "$REGION" \
    --argjson names "$batch_json" \
    '{
      "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
      contentVersion: "1.0.0.0",
      resources: [
        $names[] | {
          type: "Microsoft.Monitor/accounts",
          apiVersion: "2023-04-03",
          name: .,
          location: $location,
          tags: {
            scenario: "clustermesh-scale",
            telemetry: "control-plane",
            gc_skip: "true",
            persistent: "true"
          },
          properties: {
            publicNetworkAccess: "Enabled"
          }
        }
      ]
    }' > "$arm_template"
  batch_number=$((batch_start / amw_arm_batch_size + 1))
  deployment_name="${deployment_prefix}-${batch_number}"
  deployment_name="${deployment_name:0:64}"
  echo "Creating ${#batch_names[@]} Azure Monitor workspace(s) in ARM batch $batch_number..."
  az deployment group create \
    --resource-group "$amw_resource_group" \
    --name "$deployment_name" \
    --mode Incremental \
    --template-file "$arm_template" \
    --output none
  rm -f "$arm_template"
done

workspace_catalog_jsonl=$(mktemp)
while IFS= read -r workspace_spec; do
  workspace_name=$(echo "$workspace_spec" | jq -r '.name')
  workspace_slot=$(echo "$workspace_spec" | jq -r '.slot')
  workspace_json=$(az monitor account show \
    --resource-group "$amw_resource_group" \
    --name "$workspace_name" \
    --output json)
  workspace_id=$(echo "$workspace_json" | jq -r '.id')
  workspace_query_endpoint=$(echo "$workspace_json" | jq -r \
    '.metrics.prometheusQueryEndpoint // .properties.metrics.prometheusQueryEndpoint // empty')
  jq -cn \
    --arg slot "$workspace_slot" \
    --arg name "$workspace_name" \
    --arg id "$workspace_id" \
    --arg resource_group "$amw_resource_group" \
    --arg query_endpoint "$workspace_query_endpoint" \
    '{
      slot: $slot,
      name: $name,
      id: $id,
      resource_group: $resource_group,
      prometheus_query_endpoint: $query_endpoint,
      persistent_after_run: true
    }' >> "$workspace_catalog_jsonl"
done < <(echo "$workspace_specs" | jq -c '.[]')
workspace_catalog=$(jq -s '.' "$workspace_catalog_jsonl")
rm -f "$workspace_catalog_jsonl"

preflight_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
preflight_start=$(date -u \
  -d "$preflight_window_minutes minutes ago" \
  +%Y-%m-%dT%H:%M:%SZ)
workspace_preflight_jsonl=$(mktemp)
while IFS= read -r workspace; do
  workspace_slot=$(echo "$workspace" | jq -r '.slot')
  workspace_id=$(echo "$workspace" | jq -r '.id')
  preflight_raw="$(dirname "$MANIFEST_PATH")/amw-capacity-preflight-${workspace_slot}.json"
  preflight_summary="$(dirname "$MANIFEST_PATH")/amw-capacity-preflight-${workspace_slot}-summary.json"
  if ! capture_amw_capacity \
      "$workspace_id" \
      "$preflight_start" \
      "$preflight_end" \
      "$preflight_raw" \
      "$preflight_summary"; then
    echo "Unable to verify capacity for Azure Monitor workspace slot $workspace_slot." >&2
    exit 1
  fi
  if ! amw_capacity_preflight_ok "$preflight_summary" "$preflight_threshold"; then
    echo "##vso[task.logissue type=error;] Azure Monitor workspace slot $workspace_slot does not have enough headroom for a new control-plane telemetry run."
    exit 1
  fi
  preflight_capacity=$(cat "$preflight_summary")
  echo "$workspace" | jq -c \
    --arg threshold "$preflight_threshold" \
    --arg monitoring_window_start "$preflight_end" \
    --argjson preflight "$preflight_capacity" \
    '. + {
      capacity_guard: {
        preflight_max_utilization_percent: ($threshold | tonumber),
        monitoring_window_start: $monitoring_window_start,
        preflight: $preflight
      }
    }' >> "$workspace_preflight_jsonl"
done < <(echo "$workspace_catalog" | jq -c '.[]')
workspace_catalog=$(jq -s '.' "$workspace_preflight_jsonl")
rm -f "$workspace_preflight_jsonl"

cluster_catalog_jsonl=$(mktemp)
for row in "${source_cluster_rows[@]}"; do
  role=$(echo "$row" | jq -r '.role')
  workspace_name=$(jq -r \
    --arg role "$role" \
    '.[] | select(.role == $role) | .name' \
    <(echo "$workspace_assignments"))
  workspace=$(echo "$workspace_catalog" | jq -c \
    --arg name "$workspace_name" \
    '.[] | select(.name == $name)')
  echo "$row" | jq -c \
    --arg subscription_id "$subscription_id" \
    --arg run_id "$RUN_ID" \
    --argjson workspace "$workspace" \
    '. + {
      id: ("/subscriptions/" + $subscription_id
        + "/resourceGroups/" + .rg
        + "/providers/Microsoft.ContainerService/managedClusters/" + .name),
      prometheus_cluster_alias: (($run_id + "_" + .role)
        | gsub("[^A-Za-z0-9]"; "_")),
      workspace: $workspace
    }' >> "$cluster_catalog_jsonl"
done
clusters_with_ids=$(jq -s '.' "$cluster_catalog_jsonl")
rm -f "$cluster_catalog_jsonl"
mapfile -t cluster_rows < <(echo "$clusters_with_ids" | jq -c '.[]')

if [ "${#cluster_rows[@]}" -eq 0 ]; then
  echo "No mapped clusters found after workspace assignment." >&2
  exit 1
fi

if ! az monitor log-analytics workspace show \
    --resource-group "$amw_resource_group" \
    --workspace-name "$law_name" \
    --output none 2>/dev/null; then
  echo "Creating persistent Log Analytics workspace $law_name..."
  az monitor log-analytics workspace create \
    --resource-group "$amw_resource_group" \
    --workspace-name "$law_name" \
    --location "$law_location" \
    --retention-time "${AKS_CONTROL_PLANE_LOG_RETENTION_DAYS:-30}" \
    --tags scenario=clustermesh-scale telemetry=control-plane-logs \
    --output none
fi

law_json=$(az monitor log-analytics workspace show \
  --resource-group "$amw_resource_group" \
  --workspace-name "$law_name" \
  --output json)
law_id=$(echo "$law_json" | jq -r '.id')
law_customer_id=$(echo "$law_json" | jq -r '.customerId')

# az aks get-credentials writes the shared Azure CLI token cache. Keep this
# sequential; the later cluster updates are safe to run with bounded parallelism.
for row in "${cluster_rows[@]}"; do
  role=$(echo "$row" | jq -r '.role')
  name=$(echo "$row" | jq -r '.name')
  resource_group=$(echo "$row" | jq -r '.rg')
  kubeconfig="$HOME/.kube/$role.config"
  if [ ! -s "$kubeconfig" ]; then
    az aks get-credentials \
      --resource-group "$resource_group" \
      --name "$name" \
      --file "$kubeconfig" \
      --overwrite-existing \
      --only-show-errors
  fi
done

configure_one() {
  local row="$1"
  local role name resource_group kubeconfig metrics_enabled controlplane_enabled
  local cluster_alias rendered_config cluster_id categories_file logs_file metrics_file
  local workspace_name workspace_id
  role=$(echo "$row" | jq -r '.role')
  name=$(echo "$row" | jq -r '.name')
  resource_group=$(echo "$row" | jq -r '.rg')
  workspace_name=$(echo "$row" | jq -r '.workspace.name')
  workspace_id=$(echo "$row" | jq -r '.workspace.id')
  kubeconfig="$HOME/.kube/$role.config"
  cluster_alias=$(echo "$row" | jq -r '.prometheus_cluster_alias')
  cluster_id=$(echo "$row" | jq -r '.id')

  rendered_config=$(mktemp)
  sed \
    "s|cluster_alias = \"\"|cluster_alias = \"$cluster_alias\"|" \
    "$CONFIGMAP_PATH" > "$rendered_config"
  KUBECONFIG="$kubeconfig" kubectl create namespace monitoring \
    --dry-run=client -o yaml \
    | KUBECONFIG="$kubeconfig" kubectl apply -f - >/dev/null
  if ! KUBECONFIG="$kubeconfig" kubectl apply \
      -f "$rendered_config" >/dev/null; then
    rm -f "$rendered_config"
    return 1
  fi

  echo "[$role] enabling managed Prometheus -> $workspace_name"
  if ! az aks update \
      --resource-group "$resource_group" \
      --name "$name" \
      --enable-azure-monitor-metrics \
      --azure-monitor-workspace-resource-id "$workspace_id" \
      --only-show-errors \
      --output none; then
    rm -f "$rendered_config"
    return 1
  fi

  crd_deadline=$(( $(date +%s) + 600 ))
  until KUBECONFIG="$kubeconfig" kubectl get \
      crd/podmonitors.azmonitoring.coreos.com \
      crd/servicemonitors.azmonitoring.coreos.com >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$crd_deadline" ]; then
      echo "[$role] timed out waiting for Azure Monitor CRDs" >&2
      return 1
    fi
    sleep 10
  done
  KUBECONFIG="$kubeconfig" kubectl wait \
    --for=condition=Established \
    crd/podmonitors.azmonitoring.coreos.com \
    crd/servicemonitors.azmonitoring.coreos.com \
    --timeout=10m >/dev/null
  if ! KUBECONFIG="$kubeconfig" kubectl apply \
      -f "$rendered_config" \
      -f "$CONTROL_PLANE_MONITORS_PATH" >/dev/null; then
    rm -f "$rendered_config"
    return 1
  fi
  rm -f "$rendered_config"
  metrics_enabled=$(az aks show \
    --resource-group "$resource_group" \
    --name "$name" \
    --query azureMonitorProfile.metrics.enabled \
    -o tsv)
  controlplane_enabled=$(az aks show \
    --resource-group "$resource_group" \
    --name "$name" \
    --query azureMonitorProfile.metrics.controlPlane.enabled \
    -o tsv)
  if [ "${metrics_enabled,,}" != "true" ] || \
     [ "${controlplane_enabled,,}" != "true" ]; then
    echo "[$role] azureMonitorProfile.metrics enabled=$metrics_enabled controlPlane=$controlplane_enabled" >&2
    return 1
  fi

  categories_file=$(mktemp)
  logs_file=$(mktemp)
  metrics_file=$(mktemp)
  az monitor diagnostic-settings categories list \
    --resource "$cluster_id" \
    -o json > "$categories_file"
  jq '[
    .value[]
    | select(.categoryType == "Logs")
    | {
        category: .name,
        enabled: true,
        retentionPolicy: {enabled: false, days: 0}
      }
  ]' "$categories_file" > "$logs_file"
  jq '[
    .value[]
    | select(.categoryType == "Metrics")
    | {
        category: .name,
        enabled: true,
        retentionPolicy: {enabled: false, days: 0}
      }
  ]' "$categories_file" > "$metrics_file"
  az monitor diagnostic-settings create \
    --name "$diagnostic_setting_name" \
    --resource "$cluster_id" \
    --workspace "$law_id" \
    --export-to-resource-specific true \
    --logs @"$logs_file" \
    --metrics @"$metrics_file" \
    --output none
  jq -n \
    --arg role "$role" \
    --arg cluster_id "$cluster_id" \
    --arg diagnostic_setting_name "$diagnostic_setting_name" \
    --argjson log_categories "$(jq '[.[].category]' "$logs_file")" \
    --argjson metric_categories "$(jq '[.[].category]' "$metrics_file")" \
    '{
      role: $role,
      cluster_id: $cluster_id,
      diagnostic_setting_name: $diagnostic_setting_name,
      log_categories: $log_categories,
      metric_categories: $metric_categories
    }' > "$(dirname "$MANIFEST_PATH")/diagnostics-${role}.json"
  rm -f "$categories_file" "$logs_file" "$metrics_file"
  echo "[$role] managed Prometheus enabled with control-plane-only collection"
}

# Azure CLI commands share the MSAL token cache. Keep the safe default
# serialized; higher concurrency is an explicit opt-in after cache isolation.
concurrency="${AKS_CONTROL_PLANE_METRICS_CONCURRENCY:-1}"
if ! [[ "$concurrency" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_CONTROL_PLANE_METRICS_CONCURRENCY must be a positive integer." >&2
  exit 1
fi
pids=()
roles=()
failed=0

wait_batch() {
  local index
  for index in "${!pids[@]}"; do
    if ! wait "${pids[$index]}"; then
      echo "Managed Prometheus configuration failed for ${roles[$index]}" >&2
      failed=$((failed + 1))
    fi
  done
  pids=()
  roles=()
}

for row in "${cluster_rows[@]}"; do
  role=$(echo "$row" | jq -r '.role')
  configure_one "$row" &
  pids+=("$!")
  roles+=("$role")
  if [ "${#pids[@]}" -ge "$concurrency" ]; then
    wait_batch
  fi
done
wait_batch

if [ "$failed" -gt 0 ]; then
  echo "$failed cluster(s) failed managed Prometheus configuration." >&2
  exit 1
fi

configured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
diagnostics_json=$(jq -s '.' "$(dirname "$MANIFEST_PATH")"/diagnostics-*.json)
resource_group_count=$(echo "$clusters_with_ids" | jq '[.[].rg] | unique | length')
if [ "$resource_group_count" -eq 1 ]; then
  run_resource_group=$(echo "$clusters_with_ids" | jq -r '.[0].rg')
  resource_scope="/subscriptions/$subscription_id/resourceGroups/$run_resource_group"
else
  resource_scope="/subscriptions/$subscription_id"
fi
resource_endpoint="https://query.${REGION}.prometheus.monitor.azure.com"

jq -n \
  --arg run_id "$RUN_ID" \
  --arg configured_at "$configured_at" \
  --arg region "$REGION" \
  --arg resource_scope "$resource_scope" \
  --arg resource_endpoint "$resource_endpoint" \
  --arg amw_resource_group "$amw_resource_group" \
  --arg law_id "$law_id" \
  --arg law_name "$law_name" \
  --arg law_resource_group "$amw_resource_group" \
  --arg law_customer_id "$law_customer_id" \
  --arg law_location "$law_location" \
  --argjson workspaces "$workspace_catalog" \
  --argjson diagnostics "$diagnostics_json" \
  --argjson clusters "$clusters_with_ids" \
  '{
    schema_version: 2,
    run_id: $run_id,
    configured_at: $configured_at,
    region: $region,
    workspace: {
      mode: (if ($workspaces | length) == 1 then "single" else "per-cluster" end),
      resource_group: $amw_resource_group,
      persistent_after_run: true
    },
    workspaces: $workspaces,
    query: {
      resource_endpoint: $resource_endpoint,
      resource_scope: $resource_scope
    },
    logs: {
      workspace: {
        id: $law_id,
        name: $law_name,
        resource_group: $law_resource_group,
        customer_id: $law_customer_id,
        location: $law_location,
        persistent_after_run: true
      },
      export_to_resource_specific: true,
      diagnostics: $diagnostics,
      deferred_export: true
    },
    control_plane: {
      collection_scope: "control-plane-only",
      minimal_ingestion_profile: false,
      targets: [
        "apiserver",
        "etcd",
        "kube-scheduler",
        "kube-controller-manager",
        "cluster-autoscaler",
        "node-auto-provisioning"
      ],
      supplemental_targets: [
        "apiserver-backend-exporter",
        "prometheuscollectorhealth"
      ],
      duplicate_cluster_metrics_enabled: false,
      pod_annotation_scraping_enabled: false
    },
    processing: {
      amw_reconstruction: "deferred",
      law_export: "deferred",
      aksinfra_export: "deferred"
    },
    clusters: $clusters
  }' > "$MANIFEST_PATH"

echo "Managed Prometheus configured for ${#cluster_rows[@]} cluster(s)."
echo "Persistent workspaces: $(echo "$workspace_catalog" | jq -r 'map(.name) | join(", ")')"
echo "Run manifest: $MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_MANIFEST]$MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_CONFIGURED_AT]$configured_at"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_LAW_ID]$law_id"
