#!/bin/bash

# Nodepool helper library
# Depends on Azure CLI, jq, and common.sh for cancellation handling

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library for check_cancellation and other shared functions
source "${SCRIPT_DIR}/common.sh"

# Check if nodepool exists
nodepool_exists() {
  local cluster_name=$1
  local nodepool_name=$2
  local resource_group=$3
  az aks nodepool show \
    --cluster-name "$cluster_name" \
    --name "$nodepool_name" \
    --resource-group "$resource_group" \
    --query name -o tsv >/dev/null 2>&1
}

# Wait for nodepool to be ready
wait_for_nodepool_ready() {
  local cluster_name=$1
  local nodepool_name=$2
  local resource_group=$3
  local timeout=${4:-900}      # seconds
  local retry_interval=${5:-30}
  local elapsed=0
  local status=""

  echo "Waiting for nodepool ${nodepool_name} to be ready..."
  while [ $elapsed -lt $timeout ]; do
    if ! check_cancellation; then
      echo "WARNING: Pipeline cancelled while waiting for nodepool ${nodepool_name}"
      return 1
    fi

    status=$(az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --query "provisioningState" --output tsv 2>/dev/null || echo "QueryFailed")
    power_state=$(az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --query "powerState.code" --output tsv 2>/dev/null || echo "QueryFailed")

    echo "Nodepool ${nodepool_name} status: $status, Power state: $power_state (elapsed: ${elapsed}s)"

    case $status in
      "Succeeded")
        if [[ $power_state == "Running" ]]; then
          echo "Nodepool ${nodepool_name} is ready and running"
          return 0
        else
          echo "Nodepool succeeded but not in Running power state, waiting..."
        fi
        ;;
      "Creating"|"Scaling"|"Upgrading")
        echo "Nodepool ${nodepool_name} is still provisioning, waiting..."
        ;;
      "Failed"|"Canceled"|"Deleting"|"Deleted")
        echo "Nodepool ${nodepool_name} is in failed state: $status. Exiting."
        az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --output table || true
        return 1
        ;;
      "QueryFailed"|"")
        echo "Failed to query nodepool status. This might be temporary, continuing to wait..."
        ;;
      *)
        echo "Unknown nodepool status: $status. Continuing to wait..."
        ;;
    esac

    sleep $retry_interval
    elapsed=$((elapsed + retry_interval))
  done

  echo "Timeout reached waiting for nodepool ${nodepool_name} to be ready. Final status: $status"
  az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --output table || true
  return 1
}

# Create nodepool (idempotent) and wait for readiness
create_and_verify_nodepool() {
  local cluster_name=$1
  local nodepool_name=$2
  local resource_group=$3
  local initial_node_count=$4
  local vm_sku=${5:-${VM_SKU}}
  local node_subnet_id=$6
  local pod_subnet_id=$7
  local labels=${8:-""}
  local taints=${9:-""}
  local extra_args=${10:-""}

  if [[ -z "$vm_sku" ]]; then
    echo "ERROR: VM_SKU is not set and was not provided to create_and_verify_nodepool"
    return 1
  fi

  # Idempotent: skip creation if exists
  if nodepool_exists "$cluster_name" "$nodepool_name" "$resource_group"; then
    echo "Nodepool ${nodepool_name} already exists; skipping creation"
    return 0
  fi

  echo "Creating nodepool: $nodepool_name with $initial_node_count nodes of size $vm_sku"

  local nodepool_cmd=(az aks nodepool add --cluster-name "$cluster_name" --name "$nodepool_name" --resource-group "$resource_group")
  nodepool_cmd+=(--node-count "$initial_node_count" -s "$vm_sku" --os-sku Ubuntu)
  nodepool_cmd+=(--vnet-subnet-id "$node_subnet_id" --pod-subnet-id "$pod_subnet_id")
  nodepool_cmd+=(--tags fastpathenabled=true aks-nic-enable-multi-tenancy=true aks-nic-secondary-count="${PODS_PER_NODE}")

  local device_plugin_lc=$(echo "${DEVICE_PLUGIN:-}" | tr '[:upper:]' '[:lower:]')
  local max_pods_value="${MAX_PODS:-${max_pods:-}}"
  if [[ "${device_plugin_lc}" != "true" && "${max_pods_value}" =~ ^[0-9]+$ && "${max_pods_value}" -gt 0 ]]; then
    nodepool_cmd+=(--max-pods "${max_pods_value}")
  fi

  if [[ -n "$labels" ]]; then
    nodepool_cmd+=(--labels)
    # Split space-separated labels into individual array elements
    # shellcheck disable=SC2206
    nodepool_cmd+=($labels)
  fi

  if [[ -n "$taints" ]]; then
    nodepool_cmd+=(--node-taints "$taints")
  fi

  if [[ -n "$extra_args" ]]; then
    # shellcheck disable=SC2206
    nodepool_cmd+=($extra_args)
  fi

  local max_attempts=5
  local attempt
  for attempt in $(seq 1 $max_attempts); do
    if ! check_cancellation; then
      echo "ERROR: Pipeline cancelled during nodepool creation for ${nodepool_name}"
      return 1
    fi

    echo "Creating nodepool ${nodepool_name}: attempt $attempt/$max_attempts"
    if "${nodepool_cmd[@]}"; then
      echo "Nodepool ${nodepool_name} creation command succeeded"
      break
    else
      echo "Nodepool ${nodepool_name} creation attempt $attempt failed"
      if [[ $attempt -eq $max_attempts ]]; then
        echo "ERROR: Failed to create nodepool ${nodepool_name} after $max_attempts attempts"
        return 1
      fi
      sleep 15
    fi
  done

  wait_for_nodepool_ready "$cluster_name" "$nodepool_name" "$resource_group" 900 30
}
