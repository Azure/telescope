#!/usr/bin/env bash

set -euo pipefail

target_run_id="${CLUSTERMESH_DEBUG_TARGET_RUN_ID:?CLUSTERMESH_DEBUG_TARGET_RUN_ID is required}"
confirm="${CLUSTERMESH_DEBUG_CONFIRM_RESUME:?CLUSTERMESH_DEBUG_CONFIRM_RESUME is required}"
expected_subscription="${CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID:?CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID is required}"
region="${CLUSTERMESH_DEBUG_EXPECTED_REGION:-eastus2euap}"
artifact_dir="${CLUSTERMESH_SMOKE_ARTIFACT_DIR:?CLUSTERMESH_SMOKE_ARTIFACT_DIR is required}"
desired_state_path="${CLUSTERMESH_DEBUG_DESIRED_STATE_PATH:?CLUSTERMESH_DEBUG_DESIRED_STATE_PATH is required}"
repository_root="${REPOSITORY_ROOT:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
private_home="${AGENT_TEMPDIRECTORY:-/tmp}/n2-reuse-${target_run_id}-home"

if [ "$confirm" != "$target_run_id" ]; then
  echo "Resume confirmation mismatch." >&2
  exit 1
fi

mkdir -p "$artifact_dir"
mkdir -p "$private_home/.kube"
trap 'rm -rf "$private_home"' EXIT
export CLUSTERMESH_DEBUG_EXPECTED_SUBSCRIPTION_ID="$expected_subscription"
export CLUSTERMESH_DEBUG_EXPECTED_REGION="$region"
export CLUSTERMESH_DEBUG_EXPECTED_CLUSTER_COUNT=2
export CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256
CLUSTERMESH_DEBUG_EXPECTED_TFVARS_SHA256=$(sha256sum "$desired_state_path" | awk '{print $1}')
export CLUSTERMESH_DEBUG_EXTEND_LEASE_HOURS=24
export CLUSTERMESH_DEBUG_REQUIRE_OVERLAY_RESET=true
export CLUSTERMESH_DEBUG_MANIFEST_PATH="$artifact_dir/validation.json"

bash "$repository_root/steps/topology/clustermesh-scale/reuse/validate-existing-n100.sh"

expected_ids_sha=$(az group show --name "$target_run_id" \
  --query tags.clustermesh_debug_aks_ids_sha256 -o tsv)
current_inventory=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{role:tags.role,id:id}" \
  -o json)
current_ids_sha=$(jq -c 'sort_by(.role)' <<< "$current_inventory" | sha256sum | awk '{print $1}')
if [ "$current_ids_sha" != "$expected_ids_sha" ]; then
  echo "AKS resource IDs changed before resume." >&2
  exit 1
fi

bash "$repository_root/steps/topology/clustermesh-scale/reuse/create-staged-fleet-overlay.sh"

clusters=$(az resource list \
  --resource-group "$target_run_id" \
  --resource-type Microsoft.ContainerService/managedClusters \
  --query "[?tags.run_id=='${target_run_id}' && starts_with(tags.role, 'mesh-')].{name:name,rg:resourceGroup,role:tags.role}" \
  -o json)
printf '%s\n' "$clusters" > "$private_home/.kube/clustermesh-clusters.json"
for row in $(jq -c '.[]' <<< "$clusters"); do
  name=$(jq -r '.name' <<< "$row")
  role=$(jq -r '.role' <<< "$row")
  az aks get-credentials \
    --resource-group "$target_run_id" --name "$name" \
    --file "$private_home/.kube/$role.config" \
    --overwrite-existing --only-show-errors >/dev/null
done

HOME="$private_home" \
CLUSTERS_FILE="$private_home/.kube/clustermesh-clusters.json" \
FLEET_RG="$target_run_id" \
FLEET_NAME=clustermesh-flt \
FLEET_PROFILE=clustermesh-cmp \
CMP_STAGED_JOIN_ENABLED=true \
CMP_STAGED_JOIN_BATCH_SIZE=1 \
CMP_STAGED_JOIN_BATCH_WAIT_SECONDS=1800 \
CMP_STAGED_JOIN_TOTAL_WAIT_SECONDS=3600 \
CMP_STAGED_JOIN_POLL_SECONDS=15 \
CMP_STAGED_JOIN_CHECK_CONCURRENCY=2 \
CMP_STAGED_JOIN_RECOVERY_APPLY_AFTER_SECONDS=900 \
CMP_STAGED_JOIN_MAX_RECOVERY_APPLIES=1 \
CMP_STAGED_JOIN_RECOVERY_MIN_POST_SECONDS=300 \
CMP_STAGED_JOIN_SUMMARY_FILE="$artifact_dir/staged-enrollment.json" \
  bash "$repository_root/steps/topology/clustermesh-scale/staged-fleet-enrollment.sh"

az fleet clustermeshprofile list-members \
  --resource-group "$target_run_id" --fleet-name clustermesh-flt \
  --name clustermesh-cmp -o json > "$artifact_dir/profile-members.json"
connected=$(jq '[.[] | select(.meshProperties.status.state=="Connected")] | length' \
  "$artifact_dir/profile-members.json")
if [ "$connected" -ne 2 ]; then
  echo "Expected 2 Connected members after resume, found $connected." >&2
  exit 1
fi

jq -n --arg run_id "$target_run_id" \
  '{run_id:$run_id,result:"passed",aks_ids_preserved:true,resume_connected:2}' \
  > "$artifact_dir/summary.json"
echo "n=2 preserved-cluster resume passed for $target_run_id"
