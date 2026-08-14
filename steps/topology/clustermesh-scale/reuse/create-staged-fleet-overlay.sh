#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
expected_region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2}"
fleet_name="${CLUSTERMESH_DEBUG_FLEET_NAME:-clustermesh-flt}"
profile_name="${CLUSTERMESH_DEBUG_PROFILE_NAME:-clustermesh-cmp}"
label_key="${CMP_MEMBER_LABEL_KEY:-mesh}"
selector_value="${CMP_MEMBER_LABEL_VALUE:-true}"
initial_value="${CMP_MEMBER_INITIAL_LABEL_VALUE:-staged}"

if az fleet show --resource-group "$target_run_id" --name "$fleet_name" \
    --only-show-errors >/dev/null 2>&1; then
  echo "Fleet $fleet_name already exists; run the reset stage before resume." >&2
  exit 1
fi

clusters=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{id:id,role:tags.role}" \
  -o json)

az fleet create --resource-group "$target_run_id" --name "$fleet_name" \
  --location "$expected_region" \
  --tags owner=aks scenario=perf-eval-clustermesh-scale \
  --output none --only-show-errors

mapfile -t rows < <(jq -c 'sort_by(.role | ltrimstr("mesh-") | tonumber)[]' <<< "$clusters")
for row in "${rows[@]}"; do
  role=$(jq -r '.role' <<< "$row")
  cluster_id=$(jq -r '.id' <<< "$row")
  created=false
  for attempt in $(seq 1 30); do
    if az fleet member create \
        --resource-group "$target_run_id" --fleet-name "$fleet_name" \
        --name "$role" --member-cluster-id "$cluster_id" \
        --labels "${label_key}=${initial_value}" \
        --output none --only-show-errors; then
      created=true
      break
    fi
    sleep 20
  done
  if [ "$created" != "true" ]; then
    echo "Failed to create staged Fleet member $role." >&2
    exit 1
  fi
done

az fleet clustermeshprofile create \
  --resource-group "$target_run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" \
  --selector "${label_key}=${selector_value}" \
  --output none --only-show-errors
timeout --foreground 900s az fleet clustermeshprofile apply \
  --resource-group "$target_run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" --output none --only-show-errors

applied=$(az fleet clustermeshprofile list-members \
  --resource-group "$target_run_id" --fleet-name "$fleet_name" \
  --name "$profile_name" --query 'length(@)' -o tsv --only-show-errors)
if [ "$applied" != "0" ]; then
  echo "Expected empty staged profile before enrollment, found $applied applied members." >&2
  exit 1
fi

az group update --name "$target_run_id" \
  --set tags.clustermesh_debug_overlay_state=staged \
        tags.clustermesh_debug_resume_build="${BUILD_BUILDID:-manual}" \
  --only-show-errors >/dev/null
echo "Created empty staged Fleet overlay for ${#rows[@]} preserved AKS clusters."
