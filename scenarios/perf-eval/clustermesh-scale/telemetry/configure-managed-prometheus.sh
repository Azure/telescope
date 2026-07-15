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
: "${CUSTOM_SCRAPES_PATH:?CUSTOM_SCRAPES_PATH is required}"
: "${CUSTOM_MONITORS_PATH:?CUSTOM_MONITORS_PATH is required}"
: "${MOCK_MONITOR_PATH:?MOCK_MONITOR_PATH is required}"
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
for required_file in \
  "$CUSTOM_SCRAPES_PATH" \
  "$CUSTOM_MONITORS_PATH" \
  "$MOCK_MONITOR_PATH"; do
  if [ ! -f "$required_file" ]; then
    echo "Managed Prometheus config not found at $required_file" >&2
    exit 1
  fi
done

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
amw_name="${AKS_CONTROL_PLANE_AMW_NAME:-cmsh-scale-${REGION}-amw}"
law_name="${AKS_CONTROL_PLANE_LAW_NAME:-cmsh-scale-controlplane-law}"
law_location="${AKS_CONTROL_PLANE_LAW_LOCATION:-eastus2}"
diagnostic_setting_name="${AKS_CONTROL_PLANE_DIAGNOSTIC_SETTING_NAME:-clustermesh-scale-full-telemetry}"

if ! az group show --name "$amw_resource_group" --output none 2>/dev/null; then
  echo "Creating persistent telemetry resource group $amw_resource_group..."
  az group create \
    --name "$amw_resource_group" \
    --location "$REGION" \
    --tags scenario=clustermesh-scale telemetry=managed-prometheus \
    --output none
fi

if ! az monitor account show \
    --resource-group "$amw_resource_group" \
    --name "$amw_name" \
    --output none 2>/dev/null; then
  echo "Creating persistent Azure Monitor workspace $amw_name..."
  az monitor account create \
    --resource-group "$amw_resource_group" \
    --name "$amw_name" \
    --location "$REGION" \
    --tags scenario=clustermesh-scale telemetry=control-plane \
    --output none
fi

amw_json=$(az monitor account show \
  --resource-group "$amw_resource_group" \
  --name "$amw_name" \
  --output json)
amw_id=$(echo "$amw_json" | jq -r '.id')
amw_query_endpoint=$(echo "$amw_json" | jq -r \
  '.metrics.prometheusQueryEndpoint // .properties.metrics.prometheusQueryEndpoint // empty')

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

mapfile -t cluster_rows < <(jq -c '.[]' "$CLUSTERS_FILE")
if [ "${#cluster_rows[@]}" -eq 0 ]; then
  echo "No clusters found in $CLUSTERS_FILE" >&2
  exit 1
fi

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
  role=$(echo "$row" | jq -r '.role')
  name=$(echo "$row" | jq -r '.name')
  resource_group=$(echo "$row" | jq -r '.rg')
  kubeconfig="$HOME/.kube/$role.config"
  cluster_alias=$(printf '%s_%s' "$RUN_ID" "$role" | sed 's/[^A-Za-z0-9]/_/g')
  cluster_id="/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.ContainerService/managedClusters/${name}"

  echo "[$role] enabling managed Prometheus -> $amw_name"
  az aks update \
    --resource-group "$resource_group" \
    --name "$name" \
    --enable-azure-monitor-metrics \
    --azure-monitor-workspace-resource-id "$amw_id" \
    --only-show-errors \
    --output none

  rendered_config=$(mktemp)
  sed \
    "s|cluster_alias = \"\"|cluster_alias = \"$cluster_alias\"|" \
    "$CONFIGMAP_PATH" > "$rendered_config"
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
  KUBECONFIG="$kubeconfig" kubectl create namespace monitoring \
    --dry-run=client -o yaml \
    | KUBECONFIG="$kubeconfig" kubectl apply -f - >/dev/null
  if ! KUBECONFIG="$kubeconfig" kubectl apply \
      -f "$rendered_config" \
      -f "$CUSTOM_SCRAPES_PATH" \
      -f "$CUSTOM_MONITORS_PATH" >/dev/null; then
    rm -f "$rendered_config"
    return 1
  fi
  if KUBECONFIG="$kubeconfig" kubectl get namespace mock-clustermesh \
      >/dev/null 2>&1; then
    KUBECONFIG="$kubeconfig" kubectl apply -f "$MOCK_MONITOR_PATH" >/dev/null
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
  echo "[$role] managed Prometheus enabled and full control-plane config applied"
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
clusters_with_ids=$(jq \
  --arg subscription_id "$subscription_id" \
--arg run_id "$RUN_ID" \
'[.[] | . + {
    id: ("/subscriptions/" + $subscription_id
      + "/resourceGroups/" + .rg
      + "/providers/Microsoft.ContainerService/managedClusters/" + .name),
    prometheus_cluster_alias: (($run_id + "_" + .role)
      | gsub("[^A-Za-z0-9]"; "_"))
  }]' "$CLUSTERS_FILE")
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
  --arg amw_id "$amw_id" \
  --arg amw_name "$amw_name" \
  --arg amw_resource_group "$amw_resource_group" \
  --arg amw_query_endpoint "$amw_query_endpoint" \
  --arg law_id "$law_id" \
  --arg law_name "$law_name" \
  --arg law_resource_group "$amw_resource_group" \
  --arg law_customer_id "$law_customer_id" \
  --arg law_location "$law_location" \
  --argjson diagnostics "$diagnostics_json" \
  --argjson clusters "$clusters_with_ids" \
  '{
    schema_version: 1,
    run_id: $run_id,
    configured_at: $configured_at,
    region: $region,
    workspace: {
      id: $amw_id,
      name: $amw_name,
      resource_group: $amw_resource_group,
      prometheus_query_endpoint: $amw_query_endpoint,
      persistent_after_run: true
    },
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
      diagnostics: $diagnostics
    },
    control_plane: {
      minimal_ingestion_profile: false,
      targets: [
        "apiserver",
        "etcd",
        "kube-scheduler",
        "kube-controller-manager",
        "cluster-autoscaler",
        "node-auto-provisioning"
      ]
    },
    clusters: $clusters
  }' > "$MANIFEST_PATH"

echo "Managed Prometheus configured for ${#cluster_rows[@]} cluster(s)."
echo "Persistent workspace: $amw_id"
echo "Run manifest: $MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_MANIFEST]$MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_CONFIGURED_AT]$configured_at"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_AMW_ID]$amw_id"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_LAW_ID]$law_id"
