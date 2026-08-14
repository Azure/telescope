#!/usr/bin/env bash

set -uo pipefail

target_run_id="${RUN_ID:?RUN_ID is required}"
region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2}"
expected_count="${CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT:-100}"
tfvars_path="${CLUSTERMESH_DEBUG_TFVARS_PATH:-}"
output_path="${CLUSTERMESH_DEBUG_MANIFEST_PATH:?CLUSTERMESH_DEBUG_MANIFEST_PATH is required}"

mkdir -p "$(dirname "$output_path")"
exists=$(az group exists --name "$target_run_id" --only-show-errors 2>/dev/null || echo false)
if [ "$exists" != "true" ]; then
  jq -n --arg run_id "$target_run_id" --arg status "resource_group_absent" \
    '{run_id:$run_id,status:$status}' > "$output_path"
  exit 0
fi

tfvars_sha=""
if [ -n "$tfvars_path" ] && [ -f "$tfvars_path" ]; then
  tfvars_sha=$(sha256sum "$tfvars_path" | awk '{print $1}')
fi
deletion_due_time=$(az group show --name "$target_run_id" \
  --query tags.deletion_due_time -o tsv 2>/dev/null || true)

clusters=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{id:id,name:name,role:tags.role,location:location}" \
  -o json 2>/dev/null || echo '[]')
fleet=$(az resource list --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/fleets -o json 2>/dev/null || echo '[]')

jq -n \
  --arg run_id "$target_run_id" \
  --arg subscription_id "$(az account show --query id -o tsv 2>/dev/null || true)" \
  --arg region "$region" \
  --arg source_version "${BUILD_SOURCEVERSION:-unknown}" \
  --arg build_id "${BUILD_BUILDID:-unknown}" \
  --arg deletion_due_time "$deletion_due_time" \
  --arg tfvars_sha256 "$tfvars_sha" \
  --argjson clusters "$clusters" \
  --argjson fleet "$fleet" \
  '{
    run_id:$run_id,
    subscription_id:$subscription_id,
    region:$region,
    source_version:$source_version,
    build_id:$build_id,
    deletion_due_time:$deletion_due_time,
    tfvars_sha256:$tfvars_sha256,
    cluster_count:($clusters|length),
    clusters:$clusters,
    fleet:$fleet
  }' > "$output_path"
