#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

source "${SCRIPT_DIR}/shared-config.sh"
source "${SCRIPT_DIR}/lib/nodepool.sh"

AKS_UTILS="${REPO_ROOT}/steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh"

INITIAL_USER_NODES=${INITIAL_USER_NODES:-1}
USER_NODEPOOL_SIZE=${USER_NODEPOOL_SIZE:-500}
TARGET_USER_NODE_COUNT=${NODE_COUNT:-1}
ROLE=${ROLE:-slo}
NODE_SUBNET_ID=${NODE_SUBNET_ID:-${nodeSubnetID:-}}
POD_SUBNET_ID=${POD_SUBNET_ID:-${podSubnetID:-}}

if [[ -z "${PODS_PER_NODE:-}" ]]; then
  PODS_PER_NODE=30
  echo "PODS_PER_NODE not set; defaulting to 30"
fi

if [[ -z "${VM_SKU:-}" ]]; then
  echo "ERROR: VM_SKU is required"
  exit 1
fi

# Discover cluster if not provided
if [[ -z "${CLUSTER:-}" || -z "${RG:-}" ]]; then
  if [[ -f "$AKS_UTILS" && -n "${REGION:-}" ]]; then
    source "$AKS_UTILS"
    find_aks_cluster "$REGION" "$ROLE"
    CLUSTER="$aks_name"
    RG="$aks_rg"
  else
    echo "ERROR: CLUSTER/RG not set and REGION/ROLE not provided for discovery"
    exit 1
  fi
fi

discover_subnets() {
  if [[ -n "${NODE_SUBNET_ID:-}" && -n "${POD_SUBNET_ID:-}" ]]; then
    return 0
  fi
  echo "Discovering subnets from existing nodepool..."
  local first_nodepool_json
  first_nodepool_json=$(az aks nodepool list --cluster-name "$CLUSTER" --resource-group "$RG" --query '[0]' -o json || echo "")
  NODE_SUBNET_ID=${NODE_SUBNET_ID:-$(echo "$first_nodepool_json" | jq -r '.vnetSubnetId // empty')}
  POD_SUBNET_ID=${POD_SUBNET_ID:-$(echo "$first_nodepool_json" | jq -r '.podSubnetId // empty')}
  if [[ -z "$NODE_SUBNET_ID" ]]; then
    echo "ERROR: Unable to discover node subnet id; provide NODE_SUBNET_ID env"
    exit 1
  fi
  if [[ -z "$POD_SUBNET_ID" ]]; then
    echo "POD_SUBNET_ID not found; using NODE_SUBNET_ID"
    POD_SUBNET_ID="$NODE_SUBNET_ID"
  fi
}

discover_subnets

echo "Ensuring user nodepools for cluster=$CLUSTER rg=$RG target_nodes=$TARGET_USER_NODE_COUNT shard_size=$USER_NODEPOOL_SIZE"

if [[ -z "$TARGET_USER_NODE_COUNT" || "$TARGET_USER_NODE_COUNT" -le 0 ]]; then
  TARGET_USER_NODE_COUNT=1
fi

USER_NODEPOOL_COUNT=$(( (TARGET_USER_NODE_COUNT + USER_NODEPOOL_SIZE - 1) / USER_NODEPOOL_SIZE ))
if [[ $USER_NODEPOOL_COUNT -lt 1 ]]; then
  USER_NODEPOOL_COUNT=1
fi

existing_pools=$(az aks nodepool list --cluster-name "$CLUSTER" --resource-group "$RG" --query '[].name' -o tsv || true)

echo "Planned total user nodes: $TARGET_USER_NODE_COUNT"
echo "User nodepool shard size: $USER_NODEPOOL_SIZE"
echo "Existing pools: ${existing_pools:-<none>}"
echo "Ensuring $USER_NODEPOOL_COUNT user nodepool(s), each starting with $INITIAL_USER_NODES node"

for i in $(seq 1 $USER_NODEPOOL_COUNT); do
  if ! check_cancellation; then
    echo "ERROR: Pipeline cancelled before ensuring user nodepool $i"
    exit 143
  fi

  pool_name="userpool${i}"
  labels="slo=true testscenario=swiftv2 agentpool=${pool_name}"
  taints="slo=true:NoSchedule"

  if echo "$existing_pools" | grep -Fxq "$pool_name"; then
    echo "Nodepool $pool_name already exists"
    continue
  fi

  echo "Creating user nodepool $pool_name (1/${USER_NODEPOOL_COUNT} initial node)"
  create_and_verify_nodepool "$CLUSTER" "$pool_name" "$RG" "$INITIAL_USER_NODES" "$VM_SKU" "$NODE_SUBNET_ID" "$POD_SUBNET_ID" "$labels" "$taints"
done

# Ensure buffer pool
if [[ "${PROVISION_BUFFER_NODES:-false}" == "true" ]]; then
  buffer_pool_name="userpoolBuffer"
  labels="slo=true testscenario=swiftv2 agentpool=${buffer_pool_name}"
  taints="slo=true:NoSchedule"
  if echo "$existing_pools" | grep -Fxq "$buffer_pool_name"; then
    echo "Buffer nodepool $buffer_pool_name already exists"
  else
    echo "Creating buffer nodepool with $INITIAL_USER_NODES node"
    create_and_verify_nodepool "$CLUSTER" "$buffer_pool_name" "$RG" "$INITIAL_USER_NODES" "$VM_SKU" "$NODE_SUBNET_ID" "$POD_SUBNET_ID" "$labels" "$taints"
  fi
else
  echo "Skipping buffer nodepool creation (PROVISION_BUFFER_NODES != true)"
fi

echo "Done ensuring nodepools"
