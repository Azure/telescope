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
force_container_service_reregistration="${AKS_CONTROL_PLANE_FORCE_PROVIDER_REREGISTRATION:-false}"
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
# Bounded generation rotation: when a workspace generation is over the
# preflight threshold, retry against a small, fixed ring of alternate
# generations instead of reusing the same (possibly saturated) workspaces or
# synthesizing an unbounded, build-ID-derived resource name.
amw_rotation_enabled="${AKS_AMW_ROTATION_ENABLED:-false}"
amw_rotation_slot_count="${AKS_AMW_ROTATION_SLOT_COUNT:-1}"
amw_build_id="${BUILD_ID:-unknown}"
# Azure Monitor allows only 100 workspaces per subscription per region. A
# one-workspace-per-cluster design does not scale past small cluster counts
# (e.g. n=100 would need 100 workspaces on its own), so AMWs can be shared by
# a bounded number of clusters, and the regional headroom is checked before
# any workspace is created (see the quota guard below).
amw_clusters_per_workspace="${AKS_AMW_CLUSTERS_PER_WORKSPACE:-1}"
amw_force_shard_naming="${AKS_AMW_FORCE_SHARD_NAMING:-false}"
amw_rebalance_existing="${AKS_MANAGED_PROMETHEUS_REBALANCE_EXISTING:-false}"
amw_rebalance_settle_seconds="${AKS_AMW_REBALANCE_SETTLE_SECONDS:-600}"
amw_rebalance_window_minutes="${AKS_AMW_REBALANCE_WINDOW_MINUTES:-5}"
amw_rebalance_verify_attempts="${AKS_AMW_REBALANCE_VERIFY_ATTEMPTS:-6}"
amw_rebalance_verify_retry_seconds="${AKS_AMW_REBALANCE_VERIFY_RETRY_SECONDS:-60}"
amw_rebalance_assignment_timeout_seconds="${AKS_AMW_REBALANCE_ASSIGNMENT_TIMEOUT_SECONDS:-3600}"
amw_rebalance_assignment_poll_seconds="${AKS_AMW_REBALANCE_ASSIGNMENT_POLL_SECONDS:-60}"
amw_rebalance_assignment_request_timeout_seconds="${AKS_AMW_REBALANCE_ASSIGNMENT_REQUEST_TIMEOUT_SECONDS:-15}"
amw_default_max_active_time_series=1000000
amw_default_max_events_per_minute=1000000
amw_max_active_time_series="${AKS_AMW_MAX_ACTIVE_TIME_SERIES:-$amw_default_max_active_time_series}"
amw_max_events_per_minute="${AKS_AMW_MAX_EVENTS_PER_MINUTE:-$amw_default_max_events_per_minute}"
amw_regional_workspace_limit="${AKS_AMW_REGIONAL_WORKSPACE_LIMIT:-100}"
manifest_apply_attempts="${AKS_MANAGED_PROMETHEUS_APPLY_ATTEMPTS:-5}"
manifest_apply_retry_seconds="${AKS_MANAGED_PROMETHEUS_APPLY_RETRY_SECONDS:-15}"
# Shared across the metricsContainers deployment below and its ARM-level
# verification, so both always target the same child-resource API version.
amw_metrics_container_api_version="2025-05-03-preview"
monitor_dcr_api_version="2023-03-11"

if ! [[ "$amw_arm_batch_size" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_ARM_BATCH_SIZE must be a positive integer." >&2
  exit 1
fi
if ! [[ "$preflight_window_minutes" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_PREFLIGHT_WINDOW_MINUTES must be a positive integer." >&2
  exit 1
fi
if ! [[ "$amw_clusters_per_workspace" =~ ^[1-9][0-9]*$ ]] ||
   [ "$amw_clusters_per_workspace" -gt 10 ]; then
  echo "AKS_AMW_CLUSTERS_PER_WORKSPACE must be a positive integer no greater than 10." >&2
  exit 1
fi
for name_value in \
  "AKS_AMW_FORCE_SHARD_NAMING=$amw_force_shard_naming" \
  "AKS_MANAGED_PROMETHEUS_REBALANCE_EXISTING=$amw_rebalance_existing"; do
  name="${name_value%%=*}"
  value="${name_value#*=}"
  if [ "${value,,}" != "true" ] && [ "${value,,}" != "false" ]; then
    echo "$name must be true or false." >&2
    exit 1
  fi
done
for name_value in \
  "AKS_AMW_REBALANCE_SETTLE_SECONDS=$amw_rebalance_settle_seconds" \
  "AKS_AMW_REBALANCE_VERIFY_RETRY_SECONDS=$amw_rebalance_verify_retry_seconds" \
  "AKS_AMW_REBALANCE_ASSIGNMENT_TIMEOUT_SECONDS=$amw_rebalance_assignment_timeout_seconds" \
  "AKS_AMW_REBALANCE_ASSIGNMENT_POLL_SECONDS=$amw_rebalance_assignment_poll_seconds"; do
  name="${name_value%%=*}"
  value="${name_value#*=}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$name must be a non-negative integer." >&2
    exit 1
  fi
done
for name_value in \
  "AKS_AMW_REBALANCE_WINDOW_MINUTES=$amw_rebalance_window_minutes" \
  "AKS_AMW_REBALANCE_VERIFY_ATTEMPTS=$amw_rebalance_verify_attempts" \
  "AKS_AMW_REBALANCE_ASSIGNMENT_REQUEST_TIMEOUT_SECONDS=$amw_rebalance_assignment_request_timeout_seconds"; do
  name="${name_value%%=*}"
  value="${name_value#*=}"
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$name must be a positive integer." >&2
    exit 1
  fi
done
if ! [[ "$amw_max_active_time_series" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_MAX_ACTIVE_TIME_SERIES must be a positive integer." >&2
  exit 1
fi
if ! [[ "$amw_max_events_per_minute" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_MAX_EVENTS_PER_MINUTE must be a positive integer." >&2
  exit 1
fi
if ! [[ "$amw_regional_workspace_limit" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_AMW_REGIONAL_WORKSPACE_LIMIT must be a positive integer." >&2
  exit 1
fi
if ! [[ "$manifest_apply_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "AKS_MANAGED_PROMETHEUS_APPLY_ATTEMPTS must be a positive integer." >&2
  exit 1
fi
if ! [[ "$manifest_apply_retry_seconds" =~ ^[0-9]+$ ]]; then
  echo "AKS_MANAGED_PROMETHEUS_APPLY_RETRY_SECONDS must be a non-negative integer." >&2
  exit 1
fi

# Sort clusters deterministically by numeric mesh role (e.g. "mesh-12" -> 12)
# when the role encodes one; roles without a trailing number sort after the
# numeric ones, alphabetically. Sharing order-derived shard assignments
# (below) therefore does not depend on CLUSTERS_FILE's on-disk row order.
mapfile -t source_cluster_rows < <(
  jq -c '
    map(
      . as $row
      | ([$row.role | scan("[0-9]+")]) as $matches
      | $row + {
          _numeric_role: (
            if ($matches | length) > 0
            then ($matches[-1] | tonumber)
            else null
            end
          )
        }
    )
    | sort_by([
        (if ._numeric_role == null then 1 else 0 end),
        (._numeric_role // 0),
        .role
      ])
    | map(del(._numeric_role))
    | .[]
  ' "$CLUSTERS_FILE"
)
if [ "${#source_cluster_rows[@]}" -eq 0 ]; then
  echo "No clusters found in $CLUSTERS_FILE" >&2
  exit 1
fi
if [ -n "$legacy_amw_name" ] &&
   [ "${#source_cluster_rows[@]}" -gt 1 ]; then
  echo "AKS_CONTROL_PLANE_AMW_NAME cannot be used for a multi-cluster run; use AKS_CONTROL_PLANE_AMW_NAME_PREFIX so every cluster receives its own workspace." >&2
  exit 1
fi
if [ -n "$legacy_amw_name" ] && [ "${amw_rotation_enabled,,}" = "true" ]; then
  echo "AKS_CONTROL_PLANE_AMW_NAME cannot be combined with AKS_AMW_ROTATION_ENABLED; rotation requires per-role workspace names derived from AKS_CONTROL_PLANE_AMW_NAME_PREFIX." >&2
  exit 1
fi
if [ -n "$legacy_amw_name" ] && [ "$amw_clusters_per_workspace" -ne 1 ]; then
  echo "AKS_CONTROL_PLANE_AMW_NAME cannot be combined with AKS_AMW_CLUSTERS_PER_WORKSPACE != 1; the legacy single-workspace name already shares one workspace across every cluster." >&2
  exit 1
fi
if [ "${amw_rotation_enabled,,}" = "true" ]; then
  if ! [[ "$amw_rotation_slot_count" =~ ^[1-9][0-9]*$ ]] ||
     [ "$amw_rotation_slot_count" -gt 16 ]; then
    echo "AKS_AMW_ROTATION_SLOT_COUNT must be a positive integer no greater than 16." >&2
    exit 1
  fi
  : "${BUILD_ID:?BUILD_ID is required when AKS_AMW_ROTATION_ENABLED is true}"
  if ! [[ "$BUILD_ID" =~ ^[0-9]+$ ]]; then
    echo "BUILD_ID must be a non-negative integer when AKS_AMW_ROTATION_ENABLED is true." >&2
    exit 1
  fi
  amw_build_id="$BUILD_ID"
fi

if ! az group show --name "$amw_resource_group" --output none 2>/dev/null; then
  echo "Creating persistent telemetry resource group $amw_resource_group..."
  az group create \
    --name "$amw_resource_group" \
    --location "$REGION" \
    --tags scenario=clustermesh-scale telemetry=managed-prometheus \
    --output none
fi

# Builds the role->slot->workspace-name assignments for a candidate
# workspace-name prefix. The slot label never changes across generations;
# only the resource-name prefix does. Fails loudly (rather than truncating or
# renaming) if any derived name exceeds the Azure Monitor workspace
# 63-character limit -- this check applies identically to every candidate,
# rotation or not.
#
# When AKS_AMW_CLUSTERS_PER_WORKSPACE (amw_clusters_per_workspace) is 1, the
# slot is the (sanitized) cluster role, exactly as before -- fully backwards
# compatible with existing catalog/manifest/audit consumers and pre-existing
# per-role workspace names. When it is greater than 1, source_cluster_rows
# (already sorted deterministically by numeric mesh role) is chunked into
# consecutive groups of that size, and every row in a group maps to the same
# `shard-NNN` slot/workspace name -- multiple cluster rows referencing the
# same workspace is already handled by every downstream consumer (the
# catalog dedups by unique workspace name; the per-role lookup below just
# returns the same name for every role in the shard).
build_workspace_assignments() {
  local prefix="$1"
  local out_file row_index row role slot workspace_name shard_number
  out_file=$(mktemp)
  for row_index in "${!source_cluster_rows[@]}"; do
    row="${source_cluster_rows[$row_index]}"
    role=$(echo "$row" | jq -r '.role')
    if [ -n "$legacy_amw_name" ]; then
      workspace_name="$legacy_amw_name"
      slot="shared"
    elif [ "$amw_clusters_per_workspace" -gt 1 ] ||
         [ "${amw_force_shard_naming,,}" = "true" ]; then
      shard_number=$(( row_index / amw_clusters_per_workspace + 1 ))
      slot=$(printf 'shard-%03d' "$shard_number")
      workspace_name="${prefix}-${slot}"
    else
      slot=$(printf '%s' "$role" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')
      workspace_name="${prefix}-${slot}"
    fi
    if [ "${#workspace_name}" -gt 63 ]; then
      echo "Azure Monitor workspace name exceeds 63 characters: $workspace_name" >&2
      rm -f "$out_file"
      return 1
    fi
    jq -cn \
      --arg role "$role" \
      --arg slot "$slot" \
      --arg name "$workspace_name" \
      '{role: $role, slot: $slot, name: $name}' \
      >> "$out_file"
  done
  jq -s '.' "$out_file"
  rm -f "$out_file"
}

preflight_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
preflight_start=$(date -u \
  -d "$preflight_window_minutes minutes ago" \
  +%Y-%m-%dT%H:%M:%SZ)

amw_base_prefix="$amw_name_prefix"
amw_selected_prefix="$amw_base_prefix"
amw_generation="base"

# Bounded candidate selection happens BEFORE any workspace is created. The
# base prefix is always tried first; on a preflight failure we retry against
# a fixed-size ring of "-rN" suffixes (never an unbounded build-ID-derived
# name) starting at BUILD_ID % slot_count and wrapping exactly slot_count
# times. A candidate workspace that does not exist yet is treated as
# fresh/eligible (it still goes through the normal post-create preflight
# below); a candidate is only rejected if an EXISTING workspace in it is over
# threshold or its capacity cannot be verified (a genuine metrics-query
# failure is never treated as "fresh").
if [ "${amw_rotation_enabled,,}" = "true" ]; then
  ring_start=$(( BUILD_ID % amw_rotation_slot_count ))
  candidate_prefixes=("$amw_base_prefix")
  candidate_generations=("base")
  for ((ring_offset = 0; ring_offset < amw_rotation_slot_count; ring_offset++)); do
    ring_slot=$(( (ring_start + ring_offset) % amw_rotation_slot_count ))
    candidate_prefixes+=("${amw_base_prefix}-r${ring_slot}")
    candidate_generations+=("r${ring_slot}")
  done

  amw_selection_found=false
  for candidate_index in "${!candidate_prefixes[@]}"; do
    candidate_prefix="${candidate_prefixes[$candidate_index]}"
    candidate_generation="${candidate_generations[$candidate_index]}"
    if ! candidate_assignments=$(build_workspace_assignments "$candidate_prefix"); then
      exit 1
    fi
    candidate_names=$(echo "$candidate_assignments" | jq -r 'unique_by(.name) | .[].name')
    candidate_usable=true
    while IFS= read -r candidate_workspace_name; do
      [ -n "$candidate_workspace_name" ] || continue
      if ! az monitor account show \
          --resource-group "$amw_resource_group" \
          --name "$candidate_workspace_name" \
          --output none 2>/dev/null; then
        # Missing workspace: fresh/eligible; created + preflighted below.
        continue
      fi
      candidate_workspace_id=$(az monitor account show \
        --resource-group "$amw_resource_group" \
        --name "$candidate_workspace_name" \
        --output json | jq -r '.id')
      candidate_raw=$(mktemp)
      candidate_summary=$(mktemp)
      if capture_amw_capacity \
          "$candidate_workspace_id" \
          "$preflight_start" \
          "$preflight_end" \
          "$candidate_raw" \
          "$candidate_summary" &&
         amw_capacity_preflight_ok "$candidate_summary" "$preflight_threshold"; then
        rm -f "$candidate_raw" "$candidate_summary"
        continue
      fi
      echo "Azure Monitor workspace generation '$candidate_generation' (workspace $candidate_workspace_name) is unusable: over the ${preflight_threshold}% preflight threshold or unverifiable." >&2
      rm -f "$candidate_raw" "$candidate_summary"
      candidate_usable=false
      break
    done <<< "$candidate_names"
    if [ "$candidate_usable" = "true" ]; then
      amw_selected_prefix="$candidate_prefix"
      amw_generation="$candidate_generation"
      amw_selection_found=true
      break
    fi
  done

  if [ "$amw_selection_found" != "true" ]; then
    echo "##vso[task.logissue type=error;] All $(( amw_rotation_slot_count + 1 )) Azure Monitor workspace generation candidate(s) (base + ${amw_rotation_slot_count} bounded ring slot(s)) are over the ${preflight_threshold}% preflight threshold or unverifiable; refusing to synthesize an unbounded workspace name." >&2
    exit 1
  fi
  echo "Selected Azure Monitor workspace generation '$amw_generation' (prefix: $amw_selected_prefix)."
fi

amw_name_prefix="$amw_selected_prefix"
if ! workspace_assignments=$(build_workspace_assignments "$amw_name_prefix"); then
  exit 1
fi
workspace_specs=$(echo "$workspace_assignments" | jq 'unique_by(.name)')

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

# Azure Monitor allows only AKS_AMW_REGIONAL_WORKSPACE_LIMIT (default 100)
# Microsoft.Monitor/accounts per subscription per region. Count every
# existing account in $REGION across the WHOLE subscription (not just this
# resource group -- other scenarios/resource groups share the same regional
# quota), then fail BEFORE any ARM creation if creating the missing
# candidate workspaces would push the region over that limit. Workspaces the
# candidate already has (an existing "$amw_resource_group" account) are
# already included in the regional count, so they are not double-counted;
# only the workspaces this run still needs to CREATE are added on top.
existing_regional_workspace_count=$(
  az monitor account list --output json \
    | jq --arg region "$REGION" \
      '[.[] | select((.location // "" | ascii_downcase) == ($region | ascii_downcase))] | length'
)
missing_workspace_count=${#missing_workspace_names[@]}
projected_regional_workspace_count=$((
  existing_regional_workspace_count + missing_workspace_count
))
echo "Azure Monitor regional workspace quota for $REGION: existing=$existing_regional_workspace_count missing_candidate=$missing_workspace_count projected_total=$projected_regional_workspace_count limit=$amw_regional_workspace_limit"
if [ "$projected_regional_workspace_count" -gt "$amw_regional_workspace_limit" ]; then
  echo "##vso[task.logissue type=error;] Creating $missing_workspace_count missing Azure Monitor workspace(s) in $REGION would raise the regional Microsoft.Monitor/accounts count from $existing_regional_workspace_count to $projected_regional_workspace_count, exceeding AKS_AMW_REGIONAL_WORKSPACE_LIMIT ($amw_regional_workspace_limit)." >&2
  exit 1
fi

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
    --arg generation "$amw_generation" \
    --arg build_id "$amw_build_id" \
    --arg clusters_per_workspace "$amw_clusters_per_workspace" \
    --arg max_active_time_series "$amw_max_active_time_series" \
    --arg max_events_per_minute "$amw_max_events_per_minute" \
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
            persistent: "true",
            workspace_generation: $generation,
            created_build_id: $build_id,
            clusters_per_workspace: $clusters_per_workspace,
            requested_max_active_time_series: $max_active_time_series,
            requested_max_events_per_minute: $max_events_per_minute
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
  workspace_account_id=$(echo "$workspace_json" | jq -r \
    '.accountId // .properties.accountId // empty')
  if [ -z "$workspace_account_id" ]; then
    echo "Azure Monitor workspace $workspace_name did not expose accountId." >&2
    exit 1
  fi
  jq -cn \
    --arg slot "$workspace_slot" \
    --arg name "$workspace_name" \
    --arg id "$workspace_id" \
    --arg account_id "$workspace_account_id" \
    --arg resource_group "$amw_resource_group" \
    --arg query_endpoint "$workspace_query_endpoint" \
    --arg generation "$amw_generation" \
    --arg prefix "$amw_name_prefix" \
    --argjson clusters_per_workspace "$amw_clusters_per_workspace" \
    --argjson max_active_time_series "$amw_max_active_time_series" \
    --argjson max_events_per_minute "$amw_max_events_per_minute" \
    '{
      slot: $slot,
      name: $name,
      id: $id,
      account_id: $account_id,
      resource_group: $resource_group,
      prometheus_query_endpoint: $query_endpoint,
      persistent_after_run: true,
      generation: $generation,
      prefix: $prefix,
      clusters_per_workspace: $clusters_per_workspace,
      requested_limits: {
        max_active_time_series: $max_active_time_series,
        max_events_per_minute: $max_events_per_minute
      }
    }' >> "$workspace_catalog_jsonl"
done < <(echo "$workspace_specs" | jq -c '.[]')
workspace_catalog=$(jq -s '.' "$workspace_catalog_jsonl")
rm -f "$workspace_catalog_jsonl"

# If the requested ingestion limits differ from the Azure Monitor platform
# defaults, deploy the Microsoft.Monitor/accounts/metricsContainers child
# resource (2025-05-03-preview) for EVERY selected workspace (existing or
# newly created) so configuration is deterministic regardless of whether the
# workspace pre-existed this run. Microsoft supports auto-approved ingestion
# limit increases up to 2,000,000 via this child resource. Applied in
# amw_arm_batch_size-bounded batches, same as workspace creation above.
amw_limits_overridden=false
if [ "$amw_max_active_time_series" -ne "$amw_default_max_active_time_series" ] ||
   [ "$amw_max_events_per_minute" -ne "$amw_default_max_events_per_minute" ]; then
  amw_limits_overridden=true
  mapfile -t amw_limit_workspace_names < <(echo "$workspace_specs" | jq -r '.[].name')
  echo "Requested Azure Monitor ingestion limits (max_active_time_series=$amw_max_active_time_series, max_events_per_minute=$amw_max_events_per_minute) differ from the platform defaults; deploying metricsContainers/default overrides for ${#amw_limit_workspace_names[@]} workspace(s)."
  limits_deployment_prefix=$(printf 'cmsh-amw-limits-%s' "$RUN_ID" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')
  for ((batch_start = 0; batch_start < ${#amw_limit_workspace_names[@]}; batch_start += amw_arm_batch_size)); do
    batch_names=("${amw_limit_workspace_names[@]:batch_start:amw_arm_batch_size}")
    batch_json=$(printf '%s\n' "${batch_names[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))')
    limits_arm_template=$(mktemp)
    jq -n \
      --arg location "$REGION" \
      --arg api_version "$amw_metrics_container_api_version" \
      --argjson names "$batch_json" \
      --argjson max_active_time_series "$amw_max_active_time_series" \
      --argjson max_events_per_minute "$amw_max_events_per_minute" \
      '{
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        contentVersion: "1.0.0.0",
        resources: [
          $names[] | {
            type: "Microsoft.Monitor/accounts/metricsContainers",
            apiVersion: $api_version,
            name: (. + "/default"),
            location: $location,
            properties: {
              limits: {
                maxActiveTimeSeries: $max_active_time_series,
                maxEventsPerMinute: $max_events_per_minute
              }
            }
          }
        ]
      }' > "$limits_arm_template"
    limits_batch_number=$((batch_start / amw_arm_batch_size + 1))
    limits_deployment_name="${limits_deployment_prefix}-${limits_batch_number}"
    limits_deployment_name="${limits_deployment_name:0:64}"
    echo "Deploying ingestion limit override(s) for ${#batch_names[@]} workspace(s) in ARM batch $limits_batch_number..."
    az deployment group create \
      --resource-group "$amw_resource_group" \
      --name "$limits_deployment_name" \
      --mode Incremental \
      --template-file "$limits_arm_template" \
      --output none
    rm -f "$limits_arm_template"
  done

  # Bounded-wait/verify the requested limits actually took effect by reading
  # the Microsoft.Monitor/accounts/metricsContainers/default ARM child
  # resource directly, rather than through ingestion metrics. A freshly
  # created, unattached Azure Monitor workspace has never ingested a sample,
  # so it can legitimately emit zero ActiveTimeSeriesLimit /
  # EventsPerMinuteIngestedLimit metric data points; a metrics-based check
  # then parses that "no data" as a zero limit and fails closed even though
  # the ARM-level override already converged. Reading the limits straight
  # off the child resource sidesteps that gap. A query error or a limit that
  # never reaches the requested value still retries, then fails closed.
  amw_limit_verify_attempts="${AKS_AMW_LIMIT_VERIFY_ATTEMPTS:-6}"
  amw_limit_verify_retry_seconds="${AKS_AMW_LIMIT_VERIFY_RETRY_SECONDS:-10}"
  if ! [[ "$amw_limit_verify_attempts" =~ ^[1-9][0-9]*$ ]]; then
    echo "AKS_AMW_LIMIT_VERIFY_ATTEMPTS must be a positive integer." >&2
    exit 1
  fi
  if ! [[ "$amw_limit_verify_retry_seconds" =~ ^[0-9]+$ ]]; then
    echo "AKS_AMW_LIMIT_VERIFY_RETRY_SECONDS must be a non-negative integer." >&2
    exit 1
  fi

  while IFS= read -r workspace; do
    workspace_name=$(echo "$workspace" | jq -r '.name')
    workspace_id=$(echo "$workspace" | jq -r '.id')
    metrics_container_id="${workspace_id}/metricsContainers/default"
    limit_verified=false
    for ((limit_attempt = 1; limit_attempt <= amw_limit_verify_attempts; limit_attempt++)); do
      metrics_container_json=""
      if metrics_container_json=$(az resource show \
          --ids "$metrics_container_id" \
          --api-version "$amw_metrics_container_api_version" \
          --output json 2>/dev/null); then
        reported_active_limit=$(echo "$metrics_container_json" \
          | jq -r '.properties.limits.maxActiveTimeSeries // empty')
        reported_events_limit=$(echo "$metrics_container_json" \
          | jq -r '.properties.limits.maxEventsPerMinute // empty')
        if [ -n "$reported_active_limit" ] && [ -n "$reported_events_limit" ] &&
           awk \
             -v active="$reported_active_limit" \
             -v want_active="$amw_max_active_time_series" \
             -v events="$reported_events_limit" \
             -v want_events="$amw_max_events_per_minute" \
             'BEGIN {exit !(active >= want_active && events >= want_events)}'; then
          limit_verified=true
          break
        fi
        echo "Azure Monitor workspace $workspace_name ingestion limits not yet applied (active_time_series=${reported_active_limit:-unknown}/$amw_max_active_time_series, events_per_minute=${reported_events_limit:-unknown}/$amw_max_events_per_minute); attempt $limit_attempt/$amw_limit_verify_attempts." >&2
      else
        echo "Unable to query ingestion limits for Azure Monitor workspace $workspace_name; attempt $limit_attempt/$amw_limit_verify_attempts." >&2
      fi
      if [ "$limit_attempt" -lt "$amw_limit_verify_attempts" ] && [ "$amw_limit_verify_retry_seconds" -gt 0 ]; then
        sleep "$amw_limit_verify_retry_seconds"
      fi
    done
    if [ "$limit_verified" != "true" ]; then
      echo "##vso[task.logissue type=error;] Azure Monitor workspace $workspace_name ingestion limits did not reach the requested values (max_active_time_series>=$amw_max_active_time_series, max_events_per_minute>=$amw_max_events_per_minute) after $amw_limit_verify_attempts attempt(s); failing closed." >&2
      exit 1
    fi
    echo "Verified Azure Monitor workspace $workspace_name ingestion limits meet the requested values."
  done < <(echo "$workspace_catalog" | jq -c '.[]')
fi

# The candidate-selection preflight window computed above is reused here
# rather than resampled, so the post-create check is evaluated against the
# same headroom snapshot that made this generation eligible.
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
  rebalance_override=false
  if ! amw_capacity_preflight_ok "$preflight_summary" "$preflight_threshold"; then
    if [ "${amw_rebalance_existing,,}" != "true" ]; then
      echo "##vso[task.logissue type=error;] Azure Monitor workspace slot $workspace_slot does not have enough headroom for a new control-plane telemetry run."
      exit 1
    fi
    rebalance_override=true
    echo "##vso[task.logissue type=warning;] Azure Monitor workspace slot $workspace_slot is over the preflight threshold before one-to-one rebalance; allowing configuration to continue, but post-rebalance capacity verification remains mandatory."
  fi
  preflight_capacity=$(cat "$preflight_summary")
  echo "$workspace" | jq -c \
    --arg threshold "$preflight_threshold" \
    --arg monitoring_window_start "$preflight_end" \
    --argjson rebalance_override "$rebalance_override" \
    --argjson preflight "$preflight_capacity" \
    '. + {
      capacity_guard: {
        preflight_max_utilization_percent: ($threshold | tonumber),
        monitoring_window_start: $monitoring_window_start,
        rebalance_override: $rebalance_override,
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

wait_for_managed_monitoring_convergence() {
  local role="$1" cluster_id="$2" kubeconfig="$3" policy_before="$4"
  local enabled="${AKS_MANAGED_MONITORING_CONVERGENCE_ENABLED:-false}"
  local extension_api_version="${AKS_MANAGED_MONITORING_EXTENSION_API_VERSION:-2025-03-01}"
  local timeout_seconds="${AKS_MANAGED_MONITORING_CONVERGENCE_TIMEOUT_SECONDS:-7200}"
  local quiet_seconds="${AKS_MANAGED_MONITORING_CILIUM_QUIET_SECONDS:-120}"
  local poll_seconds="${AKS_MANAGED_MONITORING_POLL_SECONDS:-15}"
  local extension_id="${cluster_id}/providers/Microsoft.KubernetesConfiguration/extensions/aks-managed-azure-monitor-metrics"
  local deadline state cm_json ds_json policy_after desired ready updated
  local observed generation fingerprint last_fingerprint="" stable_since=0 now

  if [ "${enabled,,}" != "true" ]; then
    return 0
  fi
  for value in "$timeout_seconds" "$quiet_seconds" "$poll_seconds"; do
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
      echo "[$role] managed-monitoring convergence values must be non-negative integers" >&2
      return 1
    fi
  done

  echo "[$role] waiting for managed-monitoring extension and Cilium convergence..."
  deadline=$(( $(date +%s) + timeout_seconds ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    state=$(az resource show \
      --ids "$extension_id" \
      --api-version "$extension_api_version" \
      --query properties.provisioningState -o tsv 2>/dev/null || true)
    case "$state" in
      Succeeded)
        break
        ;;
      Failed|Canceled)
        echo "[$role] managed-monitoring extension reached terminal state $state" >&2
        return 1
        ;;
      *)
        echo "[$role] managed-monitoring extension state=${state:-not-created}; waiting ${poll_seconds}s..."
        sleep "$poll_seconds"
        ;;
    esac
  done
  if [ "${state:-}" != "Succeeded" ]; then
    echo "[$role] timed out waiting for managed-monitoring extension" >&2
    return 1
  fi

  deadline=$(( $(date +%s) + timeout_seconds ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    cm_json=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
      get configmap cilium-config -o json 2>/dev/null || true)
    ds_json=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
      get daemonset cilium -o json 2>/dev/null || true)
    if [ -z "$cm_json" ] || [ -z "$ds_json" ]; then
      last_fingerprint=""
      stable_since=0
      sleep "$poll_seconds"
      continue
    fi

    policy_after=$(jq -r '.data["enable-policy"] // ""' <<<"$cm_json")
    desired=$(jq -r '.status.desiredNumberScheduled // 0' <<<"$ds_json")
    ready=$(jq -r '.status.numberReady // 0' <<<"$ds_json")
    updated=$(jq -r '.status.updatedNumberScheduled // 0' <<<"$ds_json")
    observed=$(jq -r '.status.observedGeneration // 0' <<<"$ds_json")
    generation=$(jq -r '.metadata.generation // 0' <<<"$ds_json")
    fingerprint=$(jq -nr \
      --arg cm_rv "$(jq -r '.metadata.resourceVersion // ""' <<<"$cm_json")" \
      --arg checksum "$(jq -r '.spec.template.metadata.annotations["cilium.io/cilium-configmap-checksum"] // ""' <<<"$ds_json")" \
      --arg generation "$generation" \
      '$cm_rv + ":" + $checksum + ":" + $generation')

    if [ "$policy_after" = "never" ]; then
      echo "[$role] Cilium reconciled to enable-policy=never; ACNS DNS L7 telemetry would be invalid" >&2
      return 1
    fi
    if [ -n "$policy_before" ] && [ "$policy_after" != "$policy_before" ]; then
      echo "[$role] Cilium policy mode changed during managed-monitoring setup: $policy_before -> ${policy_after:-missing}" >&2
      return 1
    fi

    now=$(date +%s)
    if [ "$desired" -gt 0 ] &&
       [ "$ready" -eq "$desired" ] &&
       [ "$updated" -eq "$desired" ] &&
       [ "$observed" -eq "$generation" ]; then
      if [ "$fingerprint" != "$last_fingerprint" ]; then
        last_fingerprint="$fingerprint"
        stable_since="$now"
      elif [ $((now - stable_since)) -ge "$quiet_seconds" ]; then
        echo "[$role] managed-monitoring extension is Succeeded and Cilium remained stable for ${quiet_seconds}s (policy=$policy_after, desired=$desired)."
        return 0
      fi
    else
      last_fingerprint=""
      stable_since=0
    fi
    sleep "$poll_seconds"
  done

  echo "[$role] timed out waiting for a stable Cilium rollout after managed-monitoring setup" >&2
  return 1
}

kubectl_apply_with_retry() {
  local role="$1"
  local kubeconfig="$2"
  shift 2
  local attempt output rc

  for attempt in $(seq 1 "$manifest_apply_attempts"); do
    rc=0
    output=$(KUBECONFIG="$kubeconfig" kubectl apply "$@" 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
      if [ "$attempt" -gt 1 ]; then
        echo "[$role] telemetry manifest apply recovered on attempt $attempt/$manifest_apply_attempts."
      fi
      return 0
    fi

    if ! echo "$output" | grep -Eqi \
        'server is currently unable to handle the request|ServiceUnavailable|InternalError|TooManyRequests|timeout|timed out|connection reset|client connection lost|TLS handshake timeout|i/o timeout|unexpected EOF'; then
      echo "[$role] telemetry manifest apply failed with a non-transient error: $output" >&2
      return 1
    fi
    echo "[$role] transient telemetry manifest apply failure on attempt $attempt/$manifest_apply_attempts: $output" >&2
    if [ "$attempt" -lt "$manifest_apply_attempts" ]; then
      sleep "$manifest_apply_retry_seconds"
    fi
  done

  echo "[$role] telemetry manifest apply did not recover after $manifest_apply_attempts attempts." >&2
  return 1
}

normalize_resource_id() {
  tr '[:upper:]' '[:lower:]' <<<"$1"
}

configure_managed_prometheus_route() {
  local role="$1"
  local name="$2"
  local resource_group="$3"
  local cluster_id="$4"
  local workspace_name="$5"
  local workspace_id="$6"
  local workspace_account_id="$7"
  local associations association_count dcr_id dcr_url
  local dcr_file dcr_body current_workspace_id verified_workspace_id

  associations=$(az rest \
    --method get \
    --url "https://management.azure.com${cluster_id}/providers/Microsoft.Insights/dataCollectionRuleAssociations?api-version=${monitor_dcr_api_version}" \
    --output json)
  association_count=$(jq '
    [
      .value[]?
      | select(
          .name == "ContainerInsightsMetricsExtension" or
          ((.properties.dataCollectionRuleId // "") | contains("/MSProm-"))
        )
    ]
    | length
  ' <<<"$associations")
  if [ "$association_count" -gt 1 ]; then
    echo "[$role] found $association_count managed-Prometheus DCR associations; refusing an ambiguous workspace migration." >&2
    return 1
  fi
  if [ "$association_count" -eq 0 ]; then
    echo "[$role] enabling managed Prometheus -> $workspace_name"
    az aks update \
      --resource-group "$resource_group" \
      --name "$name" \
      --enable-azure-monitor-metrics \
      --azure-monitor-workspace-resource-id "$workspace_id" \
      --only-show-errors \
      --output none
    return
  fi

  dcr_id=$(jq -r '
    [
      .value[]?
      | select(
          .name == "ContainerInsightsMetricsExtension" or
          ((.properties.dataCollectionRuleId // "") | contains("/MSProm-"))
        )
      | .properties.dataCollectionRuleId
    ][0] // empty
  ' <<<"$associations")
  if [ -z "$dcr_id" ]; then
    echo "[$role] managed-Prometheus DCR association did not expose a DCR resource ID." >&2
    return 1
  fi

  dcr_url="https://management.azure.com${dcr_id}?api-version=${monitor_dcr_api_version}"
  dcr_file=$(mktemp)
  dcr_body=$(mktemp)
  if ! az rest --method get --url "$dcr_url" --output json >"$dcr_file"; then
    rm -f "$dcr_file" "$dcr_body"
    return 1
  fi
  if ! jq -e '
      (.properties.destinations.monitoringAccounts | length) == 1 and
      (.properties.dataFlows | length) >= 1 and
      any(
        .properties.dataFlows[];
        (.streams // []) | index("Microsoft-PrometheusMetrics")
      )
    ' "$dcr_file" >/dev/null; then
    echo "[$role] DCR $dcr_id does not have one unambiguous managed-Prometheus destination." >&2
    rm -f "$dcr_file" "$dcr_body"
    return 1
  fi

  current_workspace_id=$(jq -r \
    '.properties.destinations.monitoringAccounts[0].accountResourceId // empty' \
    "$dcr_file")
  if [ "$(normalize_resource_id "$current_workspace_id")" != \
       "$(normalize_resource_id "$workspace_id")" ]; then
    echo "[$role] migrating managed Prometheus DCR destination: ${current_workspace_id:-missing} -> $workspace_id"
    if ! jq \
        --arg workspace_id "$workspace_id" \
        --arg workspace_account_id "$workspace_account_id" \
        '{
          location,
          kind,
          tags,
          properties: (
            .properties
            | .destinations.monitoringAccounts[0].accountResourceId = $workspace_id
            | .destinations.monitoringAccounts[0].accountId = $workspace_account_id
          )
        }
        | if .tags == null then del(.tags) else . end' \
        "$dcr_file" >"$dcr_body" ||
       ! az rest \
          --method put \
          --url "$dcr_url" \
          --body "@$dcr_body" \
          --output none; then
      rm -f "$dcr_file" "$dcr_body"
      return 1
    fi
  else
    echo "[$role] managed Prometheus DCR already targets $workspace_name"
  fi

  if ! az rest --method get --url "$dcr_url" --output json >"$dcr_file"; then
    rm -f "$dcr_file" "$dcr_body"
    return 1
  fi
  verified_workspace_id=$(jq -r \
    '.properties.destinations.monitoringAccounts[0].accountResourceId // empty' \
    "$dcr_file")
  rm -f "$dcr_file" "$dcr_body"
  if [ "$(normalize_resource_id "$verified_workspace_id")" != \
       "$(normalize_resource_id "$workspace_id")" ]; then
    echo "[$role] DCR destination verification failed: expected=$workspace_id actual=${verified_workspace_id:-missing}" >&2
    return 1
  fi
}

verify_rebalanced_workspace_assignments() {
  local summary_path="$1"
  local expected_count="${#cluster_rows[@]}"
  local deadline token results_jsonl role cluster_alias cluster_id
  local workspace_name query_endpoint query response ready ready_count
  local remaining request_timeout sleep_seconds

  jq -n \
    --argjson expected_count "$expected_count" \
    '{
      enabled: true,
      verified: false,
      verified_at: null,
      expected_count: $expected_count,
      ready_count: 0,
      results: []
    }' >"$summary_path"
  deadline=$(( $(date +%s) + amw_rebalance_assignment_timeout_seconds ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    token=$(az account get-access-token \
      --resource https://prometheus.monitor.azure.com \
      --query accessToken -o tsv 2>/dev/null || true)
    results_jsonl=$(mktemp)
    ready_count=0
    while IFS= read -r row; do
      role=$(echo "$row" | jq -r '.role')
      cluster_alias=$(echo "$row" | jq -r '.prometheus_cluster_alias')
      cluster_id=$(echo "$row" | jq -r '.id')
      workspace_name=$(echo "$row" | jq -r '.workspace.name')
      query_endpoint=$(echo "$row" | jq -r \
        '.workspace.prometheus_query_endpoint // empty')
      if [ -z "$query_endpoint" ]; then
        query_endpoint="https://query.${REGION}.prometheus.monitor.azure.com"
      fi
      ready=false
      response=""
      remaining=$((deadline - $(date +%s)))
      if [ "$remaining" -gt 0 ] &&
         [ -n "$token" ] &&
         [ -n "$query_endpoint" ]; then
        request_timeout="$amw_rebalance_assignment_request_timeout_seconds"
        if [ "$request_timeout" -gt "$remaining" ]; then
          request_timeout="$remaining"
        fi
        query="count(apiserver_request_total{cluster=\"$cluster_alias\"})"
        response=$(curl -fsS -G \
          "${query_endpoint%/}/api/v1/query" \
          --connect-timeout 10 \
          --max-time "$request_timeout" \
          -H "Authorization: Bearer $token" \
          -H "x-ms-azure-scoping: $cluster_id" \
          --data-urlencode "query=$query" \
          2>/dev/null || true)
        if [ -z "$response" ]; then
          response='{}'
        fi
        if jq -e '
            any(
              .data.result[]?;
              ((.value // []) | length) > 1 and
              (.value[1] | tonumber? // 0) > 0
            )
          ' <<<"$response" >/dev/null 2>&1; then
          ready=true
          ready_count=$((ready_count + 1))
        fi
      fi
      jq -cn \
        --arg role "$role" \
        --arg workspace "$workspace_name" \
        --argjson ready "$ready" \
        '{role: $role, workspace: $workspace, ready: $ready}' \
        >>"$results_jsonl"
    done < <(printf '%s\n' "${cluster_rows[@]}")

    jq -n \
      --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --argjson expected_count "$expected_count" \
      --argjson ready_count "$ready_count" \
      --slurpfile results "$results_jsonl" \
      '{
        enabled: true,
        verified: ($ready_count == $expected_count),
        verified_at: $verified_at,
        expected_count: $expected_count,
        ready_count: $ready_count,
        results: $results
      }' >"$summary_path"
    rm -f "$results_jsonl"

    if [ "$ready_count" -eq "$expected_count" ]; then
      echo "One-to-one Azure Monitor workspace routing verified for all $expected_count cluster aliases."
      return 0
    fi
    echo "Waiting for one-to-one Azure Monitor workspace routing ($ready_count/$expected_count cluster aliases ready)..."
    remaining=$((deadline - $(date +%s)))
    if [ "$remaining" -le 0 ]; then
      break
    fi
    sleep_seconds="$amw_rebalance_assignment_poll_seconds"
    if [ "$sleep_seconds" -gt "$remaining" ]; then
      sleep_seconds="$remaining"
    fi
    if [ "$sleep_seconds" -gt 0 ]; then
      sleep "$sleep_seconds"
    fi
  done

  echo "One-to-one Azure Monitor workspace routing did not converge before timeout." >&2
  jq -r '.results[] | select(.ready != true) | "  \(.role) -> \(.workspace)"' \
    "$summary_path" >&2
  return 1
}

configure_one() {
  local row="$1"
  local role name resource_group kubeconfig metrics_enabled controlplane_enabled
  local cluster_alias rendered_config cluster_id categories_file logs_file metrics_file
  local workspace_name workspace_id workspace_account_id
  local cilium_policy_before namespace_manifest
  role=$(echo "$row" | jq -r '.role')
  name=$(echo "$row" | jq -r '.name')
  resource_group=$(echo "$row" | jq -r '.rg')
  workspace_name=$(echo "$row" | jq -r '.workspace.name')
  workspace_id=$(echo "$row" | jq -r '.workspace.id')
  workspace_account_id=$(echo "$row" | jq -r '.workspace.account_id')
  kubeconfig="$HOME/.kube/$role.config"
  cluster_alias=$(echo "$row" | jq -r '.prometheus_cluster_alias')
  cluster_id=$(echo "$row" | jq -r '.id')
  cilium_policy_before=$(KUBECONFIG="$kubeconfig" kubectl -n kube-system \
    get configmap cilium-config -o jsonpath='{.data.enable-policy}' \
    2>/dev/null || true)

  rendered_config=$(mktemp)
  namespace_manifest=$(mktemp)
  sed \
    "s|cluster_alias = \"\"|cluster_alias = \"$cluster_alias\"|" \
    "$CONFIGMAP_PATH" > "$rendered_config"
  if ! KUBECONFIG="$kubeconfig" kubectl create namespace monitoring \
      --dry-run=client -o yaml >"$namespace_manifest"; then
    rm -f "$namespace_manifest" "$rendered_config"
    return 1
  fi
  if ! kubectl_apply_with_retry "$role" "$kubeconfig" \
      -f "$namespace_manifest"; then
    rm -f "$namespace_manifest" "$rendered_config"
    return 1
  fi
  rm -f "$namespace_manifest"
  if ! kubectl_apply_with_retry "$role" "$kubeconfig" \
      -f "$rendered_config"; then
    rm -f "$rendered_config"
    return 1
  fi

  if ! configure_managed_prometheus_route \
      "$role" \
      "$name" \
      "$resource_group" \
      "$cluster_id" \
      "$workspace_name" \
      "$workspace_id" \
      "$workspace_account_id"; then
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
  if ! kubectl_apply_with_retry "$role" "$kubeconfig" \
      -f "$rendered_config" \
      -f "$CONTROL_PLANE_MONITORS_PATH"; then
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
  if ! wait_for_managed_monitoring_convergence \
      "$role" "$cluster_id" "$kubeconfig" "$cilium_policy_before"; then
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

rebalance_assignment_summary="$(dirname "$MANIFEST_PATH")/amw-rebalance-assignment.json"
if [ "${amw_rebalance_existing,,}" = "true" ]; then
  if [ "$amw_rebalance_settle_seconds" -gt 0 ]; then
    echo "Waiting ${amw_rebalance_settle_seconds}s for one-to-one Azure Monitor workspace rebalance to settle."
    sleep "$amw_rebalance_settle_seconds"
  fi
  if ! verify_rebalanced_workspace_assignments \
      "$rebalance_assignment_summary"; then
    echo "##vso[task.logissue type=error;] One-to-one Azure Monitor workspace routing did not converge." >&2
    exit 1
  fi
  rebalance_capacity_verified=false
  for attempt in $(seq 1 "$amw_rebalance_verify_attempts"); do
    rebalance_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    rebalance_start=$(date -u \
      -d "$amw_rebalance_window_minutes minutes ago" \
      +%Y-%m-%dT%H:%M:%SZ)
    rebalance_failed_slots=()
    while IFS= read -r workspace; do
      workspace_slot=$(echo "$workspace" | jq -r '.slot')
      workspace_id=$(echo "$workspace" | jq -r '.id')
      rebalance_raw="$(dirname "$MANIFEST_PATH")/amw-capacity-rebalance-${workspace_slot}-attempt-${attempt}.json"
      rebalance_summary="$(dirname "$MANIFEST_PATH")/amw-capacity-rebalance-${workspace_slot}-attempt-${attempt}-summary.json"
      if ! capture_amw_capacity \
          "$workspace_id" \
          "$rebalance_start" \
          "$rebalance_end" \
          "$rebalance_raw" \
          "$rebalance_summary" ||
         ! amw_capacity_rebalance_ok "$rebalance_summary" "$preflight_threshold"; then
        rebalance_failed_slots+=("$workspace_slot")
      fi
    done < <(echo "$workspace_catalog" | jq -c '.[]')

    if [ "${#rebalance_failed_slots[@]}" -eq 0 ]; then
      rebalance_capacity_verified=true
      echo "One-to-one Azure Monitor workspace rebalance capacity verified across $(echo "$workspace_catalog" | jq 'length') workspace(s)."
      break
    fi
    echo "Post-rebalance capacity verification attempt $attempt/$amw_rebalance_verify_attempts still failed for ${#rebalance_failed_slots[@]} workspace(s): ${rebalance_failed_slots[*]}" >&2
    if [ "$attempt" -lt "$amw_rebalance_verify_attempts" ] &&
       [ "$amw_rebalance_verify_retry_seconds" -gt 0 ]; then
      sleep "$amw_rebalance_verify_retry_seconds"
    fi
  done
  if [ "$rebalance_capacity_verified" != "true" ]; then
    echo "##vso[task.logissue type=error;] One-to-one Azure Monitor workspace rebalance did not reach the required no-drop capacity state." >&2
    exit 1
  fi
else
  jq -n '{
    enabled: false,
    verified: true,
    verified_at: null,
    expected_count: 0,
    ready_count: 0,
    results: []
  }' >"$rebalance_assignment_summary"
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
if [ "${amw_rotation_enabled,,}" = "true" ]; then
  amw_rotation_enabled_json=true
else
  amw_rotation_enabled_json=false
fi
if [ "$amw_limits_overridden" = "true" ]; then
  amw_limits_overridden_json=true
else
  amw_limits_overridden_json=false
fi

# Large JSON blobs (workspace catalog, diagnostics, clusters) can each
# exceed the kernel's per-argument length limit (MAX_ARG_STRLEN, 128KiB on
# Linux) once cluster counts reach the dozens-to-hundreds range (e.g. n100),
# causing `jq: Argument list too long`. Pass them via --slurpfile (reads
# from a file, not argv) instead of --argjson (reads from a command-line
# argument) to stay correct at scale.
manifest_workspaces_file=$(mktemp)
manifest_diagnostics_file=$(mktemp)
manifest_clusters_file=$(mktemp)
manifest_rebalance_assignment_file=$(mktemp)
printf '%s' "$workspace_catalog" >"$manifest_workspaces_file"
printf '%s' "$diagnostics_json" >"$manifest_diagnostics_file"
printf '%s' "$clusters_with_ids" >"$manifest_clusters_file"
cat "$rebalance_assignment_summary" >"$manifest_rebalance_assignment_file"

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
  --slurpfile workspaces_arr "$manifest_workspaces_file" \
  --slurpfile diagnostics_arr "$manifest_diagnostics_file" \
  --slurpfile clusters_arr "$manifest_clusters_file" \
  --slurpfile rebalance_assignment_arr "$manifest_rebalance_assignment_file" \
  --arg amw_base_prefix "$amw_base_prefix" \
  --arg amw_selected_prefix "$amw_name_prefix" \
  --arg amw_generation "$amw_generation" \
  --argjson amw_rotation_enabled "$amw_rotation_enabled_json" \
  --argjson amw_rotation_slot_count "$amw_rotation_slot_count" \
  --arg amw_build_id "$amw_build_id" \
  --argjson amw_clusters_per_workspace "$amw_clusters_per_workspace" \
  --argjson amw_max_active_time_series "$amw_max_active_time_series" \
  --argjson amw_max_events_per_minute "$amw_max_events_per_minute" \
  --argjson amw_limits_overridden "$amw_limits_overridden_json" \
  --argjson amw_regional_workspace_limit "$amw_regional_workspace_limit" \
  --argjson amw_existing_regional_workspace_count "$existing_regional_workspace_count" \
  --argjson amw_missing_workspace_count "$missing_workspace_count" \
  --argjson amw_projected_regional_workspace_count "$projected_regional_workspace_count" \
  '($workspaces_arr[0]) as $workspaces |
  ($diagnostics_arr[0]) as $diagnostics |
  ($clusters_arr[0]) as $clusters |
  ($rebalance_assignment_arr[0]) as $rebalance_assignment |
  {
    schema_version: 2,
    run_id: $run_id,
    configured_at: $configured_at,
    region: $region,
    workspace: {
      mode: (if ($workspaces | length) == 1 then "single" else "per-cluster" end),
      resource_group: $amw_resource_group,
      persistent_after_run: true
    },
    workspace_rotation: {
      enabled: $amw_rotation_enabled,
      slot_count: $amw_rotation_slot_count,
      base_prefix: $amw_base_prefix,
      selected_prefix: $amw_selected_prefix,
      generation: $amw_generation,
      build_id: $amw_build_id
    },
    workspace_sharding: {
      clusters_per_workspace: $amw_clusters_per_workspace,
      cluster_count: ($clusters | length),
      workspace_count: ($workspaces | length)
    },
    workspace_rebalance_assignment: $rebalance_assignment,
    workspace_ingestion_limits: {
      max_active_time_series: $amw_max_active_time_series,
      max_events_per_minute: $amw_max_events_per_minute,
      overrides_requested: $amw_limits_overridden
    },
    workspace_regional_quota: {
      region: $region,
      limit: $amw_regional_workspace_limit,
      existing_before_run: $amw_existing_regional_workspace_count,
      created_this_run: $amw_missing_workspace_count,
      projected_total: $amw_projected_regional_workspace_count
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

rm -f \
  "$manifest_workspaces_file" \
  "$manifest_diagnostics_file" \
  "$manifest_clusters_file" \
  "$manifest_rebalance_assignment_file"

echo "Managed Prometheus configured for ${#cluster_rows[@]} cluster(s)."
echo "Persistent workspaces: $(echo "$workspace_catalog" | jq -r 'map(.name) | join(", ")')"
echo "Run manifest: $MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_MANIFEST]$MANIFEST_PATH"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_METRICS_CONFIGURED_AT]$configured_at"
echo "##vso[task.setvariable variable=AKS_CONTROL_PLANE_LAW_ID]$law_id"
