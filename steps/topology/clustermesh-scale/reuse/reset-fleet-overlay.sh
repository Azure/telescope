#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
confirm="${CLUSTERMESH_DEBUG_CONFIRM_RESET:?CLUSTERMESH_DEBUG_CONFIRM_RESET is required}"
fleet_name="${CLUSTERMESH_DEBUG_FLEET_NAME:-clustermesh-flt}"
profile_name="${CLUSTERMESH_DEBUG_PROFILE_NAME:-clustermesh-cmp}"
label_key="${CMP_MEMBER_LABEL_KEY:-mesh}"
expected_count="${CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT:-100}"

if [ "$confirm" != "$target_run_id" ]; then
  echo "Reset confirmation mismatch: CLUSTERMESH_DEBUG_CONFIRM_RESET must equal $target_run_id." >&2
  exit 1
fi
if ! [[ "$expected_count" =~ ^[1-9][0-9]*$ ]]; then
  echo "CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT must be a positive integer." >&2
  exit 1
fi

if ! az fleet show --resource-group "$target_run_id" --name "$fleet_name" \
    --only-show-errors >/dev/null 2>&1; then
  echo "Fleet $fleet_name is already absent; overlay reset is complete."
  az group update --name "$target_run_id" \
    --set tags.clustermesh_debug_overlay_state=reset \
          tags.clustermesh_debug_reset_build="${BUILD_BUILDID:-manual}" \
    --only-show-errors >/dev/null
  exit 0
fi

mapfile -t members < <(az fleet member list \
  --resource-group "$target_run_id" --fleet-name "$fleet_name" \
  --query '[].name' -o tsv --only-show-errors)
member_json=$(az fleet member list \
  --resource-group "$target_run_id" --fleet-name "$fleet_name" \
  -o json --only-show-errors)
cluster_json=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{name:tags.role,clusterResourceId:id}" \
  -o json)
if ! jq -e -n \
    --argjson members "$member_json" \
    --argjson clusters "$cluster_json" \
    --argjson expected_count "$expected_count" '
      ($clusters
        | map({key:.name, value:(.clusterResourceId | ascii_downcase)})
        | from_entries) as $expected_map
      | ($members
        | map({key:.name, value:(.clusterResourceId | ascii_downcase)})
        | from_entries) as $actual
      | ($members | length) == $expected_count
        and ($actual | length) == $expected_count
        and $actual == $expected_map
    ' >/dev/null; then
  echo "Fleet member inventory does not exactly match the validated mesh-1..mesh-$expected_count AKS resources; refusing reset." >&2
  exit 1
fi

if az fleet clustermeshprofile show \
    --resource-group "$target_run_id" --fleet-name "$fleet_name" \
    --name "$profile_name" --only-show-errors >/dev/null 2>&1; then
  for member in "${members[@]}"; do
    az fleet member update \
      --resource-group "$target_run_id" --fleet-name "$fleet_name" \
      --name "$member" --labels "${label_key}=detaching" \
      --output none --only-show-errors
  done

  timeout --foreground 900s az fleet clustermeshprofile apply \
    --resource-group "$target_run_id" --fleet-name "$fleet_name" \
    --name "$profile_name" --output none --only-show-errors || true

  drain_deadline=$(( $(date +%s) + 3600 ))
  next_apply_at=$(( $(date +%s) + 300 ))
  while [ "$(date +%s)" -lt "$drain_deadline" ]; do
    applied=$(az fleet clustermeshprofile list-members \
      --resource-group "$target_run_id" --fleet-name "$fleet_name" \
      --name "$profile_name" --query 'length(@)' -o tsv \
      --only-show-errors 2>/dev/null || echo unknown)
    echo "Fleet overlay drain: applied=$applied"
    if [ "$applied" = "0" ]; then
      break
    fi
    now=$(date +%s)
    if [ "$now" -ge "$next_apply_at" ]; then
      profile_state=$(az fleet clustermeshprofile show \
        --resource-group "$target_run_id" --fleet-name "$fleet_name" \
        --name "$profile_name" --query properties.provisioningState \
        -o tsv --only-show-errors 2>/dev/null || echo unknown)
      if [[ "$profile_state" =~ ^(Applying|Updating|Creating)$ ]]; then
        echo "Fleet overlay drain: profile remains $profile_state; deferring apply nudge."
      else
        echo "Fleet overlay drain: profile=$profile_state applied=$applied; issuing bounded apply nudge."
        timeout --foreground 300s az fleet clustermeshprofile apply \
          --resource-group "$target_run_id" --fleet-name "$fleet_name" \
          --name "$profile_name" --output none --only-show-errors || true
      fi
      next_apply_at=$(( $(date +%s) + 300 ))
    fi
    sleep 15
  done
  if [ "${applied:-unknown}" != "0" ]; then
    echo "Fleet overlay did not drain within 3600s; preserving RG for manual diagnosis." >&2
    exit 1
  fi

  timeout --foreground 900s az fleet clustermeshprofile delete \
    --resource-group "$target_run_id" --fleet-name "$fleet_name" \
    --name "$profile_name" --yes --output none --only-show-errors
  profile_delete_deadline=$(( $(date +%s) + 900 ))
  while [ "$(date +%s)" -lt "$profile_delete_deadline" ]; do
    if ! az fleet clustermeshprofile show \
        --resource-group "$target_run_id" --fleet-name "$fleet_name" \
        --name "$profile_name" --only-show-errors >/dev/null 2>&1; then
      break
    fi
    sleep 10
  done
  if az fleet clustermeshprofile show \
      --resource-group "$target_run_id" --fleet-name "$fleet_name" \
      --name "$profile_name" --only-show-errors >/dev/null 2>&1; then
    echo "ClusterMeshProfile $profile_name still exists after delete." >&2
    exit 1
  fi
fi

for member in "${members[@]}"; do
  az fleet member delete \
    --resource-group "$target_run_id" --fleet-name "$fleet_name" \
    --name "$member" --yes --output none --only-show-errors
done

timeout --foreground 900s az fleet delete \
  --resource-group "$target_run_id" --name "$fleet_name" \
  --yes --output none --only-show-errors

if az fleet show --resource-group "$target_run_id" --name "$fleet_name" \
    --only-show-errors >/dev/null 2>&1; then
  echo "Fleet $fleet_name still exists after reset." >&2
  exit 1
fi

az group update --name "$target_run_id" \
  --set tags.clustermesh_debug_overlay_state=reset \
        tags.clustermesh_debug_reset_build="${BUILD_BUILDID:-manual}" \
  --only-show-errors >/dev/null
echo "Fleet overlay reset complete; AKS clusters and networking were not modified."
