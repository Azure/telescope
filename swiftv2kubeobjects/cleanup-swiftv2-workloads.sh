#!/bin/bash
set -euo pipefail

# =============================================================================
# Cleanup script for swiftv2 workloads and nodepools
# This script:
# 1. Finds AKS cluster in the resource group (if not provided)
# 2. Deletes all deployments/pods created by swiftv2_deployment_*_scale_config.yaml
# 3. Deletes user nodepools one at a time
#
# Environment variables:
#   RG or RESOURCE_GROUP_NAME - Resource group name (required)
#   CLUSTER                   - AKS cluster name (optional, auto-discovered)
#   DELETE_NODEPOOLS          - Whether to delete nodepools (default: true)
#   DELETE_BUFFER_POOL        - Whether to delete buffer pool (default: true)
#   GROUP_NAME                - Pod group label to match (default: deployment-churn)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/lib/common.sh"

# Source shared config if available
if [[ -f "${SCRIPT_DIR}/shared-config.sh" ]]; then
    source "${SCRIPT_DIR}/shared-config.sh"
fi

# Configuration with defaults
RG="${RG:-${RESOURCE_GROUP_NAME:-}}"
GROUP_NAME=${GROUP_NAME:-deployment-churn}
DELETE_NODEPOOLS=${DELETE_NODEPOOLS:-true}
DELETE_BUFFER_POOL=${DELETE_BUFFER_POOL:-true}

# Validate required inputs
if [[ -z "$RG" ]]; then
    echo "ERROR: RG or RESOURCE_GROUP_NAME environment variable is required"
    exit 1
fi

if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    echo "ERROR: AZURE_SUBSCRIPTION_ID environment variable is required"
    exit 1
fi

# Set the Azure subscription
echo "Setting Azure subscription to: $AZURE_SUBSCRIPTION_ID"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"

# Set up cancellation trap
trap handle_cancellation SIGTERM SIGINT

# =============================================================================
# CLUSTER DISCOVERY
# =============================================================================

echo "==================================================================="
echo "Swiftv2 Workload Cleanup"
echo "Resource Group: $RG"
echo "==================================================================="

# Discover cluster if not provided
if [[ -z "${CLUSTER:-}" ]]; then
    echo "Discovering AKS cluster in resource group $RG..."
    CLUSTER=$(az aks list -g "$RG" --query "[0].name" -o tsv 2>/dev/null || true)
    
    if [[ -z "$CLUSTER" ]]; then
        echo "No AKS cluster found in resource group $RG. Nothing to clean up."
        exit 0
    fi
fi

echo "Found AKS cluster: $CLUSTER"
echo "==================================================================="

# Get credentials for kubectl
echo "Getting AKS credentials..."
az aks get-credentials -n "$CLUSTER" -g "$RG" --admin --overwrite-existing

# =============================================================================
# STEP 1: DELETE DEPLOYMENTS AND PODS
# =============================================================================
echo ""
echo "==================================================================="
echo "Step 1: Deleting deployments created by swiftv2 configs"
echo "==================================================================="

# Delete deployments with the deployment-churn group label pattern
# These are created by both static and dynamic configs with pattern:
# group={{$groupName}}-job{{$jobIndex}}-{{$j}}
echo "Deleting deployments with label selector: podgroup=$GROUP_NAME"

# Get all namespaces matching slo-job prefix (slo-job0-1, slo-job1-1, etc.)
for ns in $(kubectl get namespaces -o name 2>/dev/null | grep "namespace/slo-job" | cut -d/ -f2 || true); do
    if ! check_cancellation; then
        exit 143
    fi

    echo "Processing namespace: $ns"

    # Delete deployments matching the pattern (deployment-churn-job*)
    deployments=$(kubectl get deployments -n "$ns" -l "podgroup=$GROUP_NAME" -o name 2>/dev/null || true)
    if [[ -n "$deployments" ]]; then
        echo "Deleting deployments in namespace $ns:"
        echo "$deployments"
        kubectl delete deployments -n "$ns" -l "podgroup=$GROUP_NAME" --wait=false || true
    fi

    # Also delete any remaining pods with the podgroup label
    pods=$(kubectl get pods -n "$ns" -l "podgroup=$GROUP_NAME" -o name 2>/dev/null || true)
    if [[ -n "$pods" ]]; then
        echo "Deleting remaining pods in namespace $ns with label podgroup=$GROUP_NAME"
        kubectl delete pods -n "$ns" -l "podgroup=$GROUP_NAME" --grace-period=0 --force 2>/dev/null || true
    fi
done

# Wait for deployments to be deleted
echo "Waiting for deployments to be fully deleted..."
sleep 30

for ns in $(kubectl get namespaces -o name 2>/dev/null | grep "namespace/slo-job" | cut -d/ -f2 || true); do
    remaining=$(kubectl get deployments -n "$ns" -l "podgroup=$GROUP_NAME" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$remaining" -gt 0 ]]; then
        echo "Waiting for $remaining deployments to terminate in namespace $ns..."
        kubectl wait --for=delete deployment -n "$ns" -l "podgroup=$GROUP_NAME" --timeout=300s 2>/dev/null || true
    fi
done

# =============================================================================
# STEP 2: DELETE USER NODEPOOLS ONE AT A TIME
# =============================================================================
if [[ "$DELETE_NODEPOOLS" == "true" ]]; then
    echo ""
    echo "==================================================================="
    echo "Step 2: Deleting user nodepools one at a time"
    echo "==================================================================="

    # Get list of user nodepools (userpool1, userpool2, etc. and userpoolBuffer)
    existing_pools=$(az aks nodepool list --cluster-name "$CLUSTER" --resource-group "$RG" --query '[].name' -o tsv 2>/dev/null || true)

    # Separate user pools and buffer pool
    user_pools=""
    buffer_pool=""

    for pool in $existing_pools; do
        if [[ "$pool" == "userpoolBuffer" ]]; then
            buffer_pool="$pool"
        elif [[ "$pool" =~ ^userpool[0-9]+$ ]]; then
            user_pools="$user_pools $pool"
        fi
    done

    # Delete regular user pools first (in reverse order for cleaner shutdown)
    user_pools_sorted=$(echo "$user_pools" | tr ' ' '\n' | grep -v '^$' | sort -t'l' -k2 -rn || true)

    for pool_name in $user_pools_sorted; do
        if ! check_cancellation; then
            echo "ERROR: Pipeline cancelled before deleting nodepool $pool_name"
            exit 143
        fi

        echo ""
        echo "Deleting nodepool: $pool_name"
        
        # Start deletion
        if az aks nodepool delete --cluster-name "$CLUSTER" --name "$pool_name" -g "$RG" --no-wait 2>/dev/null; then
            echo "Deletion initiated for nodepool $pool_name"
            
            # Wait for this nodepool to be deleted before moving to next
            if ! wait_for_nodepool_deletion "$CLUSTER" "$pool_name" "$RG" 900; then
                echo "WARNING: Nodepool $pool_name deletion did not complete within timeout, continuing..."
            fi
        else
            echo "WARNING: Failed to initiate deletion for nodepool $pool_name"
        fi
    done

    # Delete buffer pool last if requested
    if [[ "$DELETE_BUFFER_POOL" == "true" && -n "$buffer_pool" ]]; then
        if ! check_cancellation; then
            echo "ERROR: Pipeline cancelled before deleting buffer nodepool"
            exit 143
        fi

        echo ""
        echo "Deleting buffer nodepool: $buffer_pool"
        
        if az aks nodepool delete --cluster-name "$CLUSTER" --name "$buffer_pool" -g "$RG" --no-wait 2>/dev/null; then
            echo "Deletion initiated for buffer nodepool $buffer_pool"
            
            if ! wait_for_nodepool_deletion "$CLUSTER" "$buffer_pool" "$RG" 900; then
                echo "WARNING: Buffer nodepool deletion did not complete within timeout"
            fi
        else
            echo "WARNING: Failed to initiate deletion for buffer nodepool $buffer_pool"
        fi
    fi
else
    echo ""
    echo "Skipping nodepool deletion (DELETE_NODEPOOLS != true)"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "==================================================================="
echo "Cleanup completed!"
echo "==================================================================="

# Show remaining resources
echo ""
echo "Remaining nodepools:"
az aks nodepool list --cluster-name "$CLUSTER" --resource-group "$RG" --query '[].{Name:name, Count:count, VMSize:vmSize}' -o table 2>/dev/null || echo "Unable to list nodepools"

echo ""
echo "Remaining pods in slo-job namespaces:"
for ns in $(kubectl get namespaces -o name 2>/dev/null | grep "namespace/slo-job" | cut -d/ -f2 || true); do
    count=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | wc -l || echo "0")
    echo "  $ns: $count pods"
done

echo ""
echo "Done!"
