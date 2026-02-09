#!/bin/bash
# NOTE: This script is designed to be resilient - it will continue on errors
# since subsequent scripts will cleanup the AKS cluster and resource group anyway.
# We use 'set +e' to prevent the script from exiting on failures.
set +e

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
CLEANUP_BATCH_SIZE=${CLEANUP_BATCH_SIZE:-500}

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

# NOTE: We intentionally do NOT trap SIGTERM/SIGINT here.
# This cleanup script should run to completion even if the pipeline is cancelled,
# as it helps free up resources. Subsequent scripts will cleanup cluster/RG anyway.

# =============================================================================
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
# staticres: 1 deployment = 1 pod
# dynamicres: 1 deployment = N pods (pods_per_step, typically 50)
# We batch delete targeting ~CLEANUP_BATCH_SIZE pods at a time for consistent behavior
echo "Deleting deployments with label selector: podgroup=$GROUP_NAME (batch size: $CLEANUP_BATCH_SIZE)"

# Get all namespaces matching slo-job prefix (slo-job0-1, slo-job1-1, etc.)
for ns in $(kubectl get namespaces -o name 2>/dev/null | grep "namespace/slo-job" | cut -d/ -f2 || true); do
    echo ""
    echo "Processing namespace: $ns"

    # Get deployment names and their replica counts (pod count)
    # Format: "deployment-name replica-count" per line
    deployments_info=$(kubectl get deployments -n "$ns" -l "podgroup=$GROUP_NAME" \
        -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.replicas}{"\n"}{end}' 2>/dev/null || true)
    
    if [[ -z "$deployments_info" ]]; then
        echo "  No deployments found in namespace $ns"
        continue
    fi

    total_deployments=$(echo "$deployments_info" | wc -l)
    total_pods=$(echo "$deployments_info" | awk '{sum += $2} END {print sum}')
    echo "  Found $total_deployments deployments with $total_pods total pods"

    # Batch deployments by pod count (target ~500 pods per batch)
    batch_deployments=""
    batch_pod_count=0
    batch_num=1
    deleted_pods=0

    while IFS= read -r line; do
        dep_name=$(echo "$line" | awk '{print $1}')
        dep_replicas=$(echo "$line" | awk '{print $2}')
        
        # Handle empty or invalid lines
        if [[ -z "$dep_name" || -z "$dep_replicas" ]]; then
            continue
        fi

        # Add deployment to current batch
        batch_deployments="$batch_deployments $dep_name"
        batch_pod_count=$((batch_pod_count + dep_replicas))

        # If batch reaches target pod count, delete the batch
        if [[ $batch_pod_count -ge $CLEANUP_BATCH_SIZE ]]; then
            echo "  Deleting batch $batch_num (~$batch_pod_count pods)..."
            retry_command 3 5 "kubectl delete deployments -n $ns $batch_deployments --wait=false" || true
            deleted_pods=$((deleted_pods + batch_pod_count))
            
            # Reset batch
            batch_deployments=""
            batch_pod_count=0
            batch_num=$((batch_num + 1))
            
            # Small delay between batches to avoid API throttling
            sleep 1
        fi
    done <<< "$deployments_info"

    # Delete remaining deployments in the last batch
    if [[ -n "$batch_deployments" ]]; then
        echo "  Deleting final batch $batch_num (~$batch_pod_count pods)..."
        retry_command 3 5 "kubectl delete deployments -n $ns $batch_deployments --wait=false" || true
        deleted_pods=$((deleted_pods + batch_pod_count))
    fi

    echo "  Initiated deletion for $deleted_pods pods across $batch_num batches in namespace $ns"

    # Force delete any remaining pods that might be orphaned
    remaining_pods=$(kubectl get pods -n "$ns" -l "podgroup=$GROUP_NAME" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$remaining_pods" -gt 0 ]]; then
        echo "  Force deleting $remaining_pods remaining pods..."
        kubectl delete pods -n "$ns" -l "podgroup=$GROUP_NAME" --grace-period=0 --force 2>/dev/null || true
    fi

    # Wait for deployments to terminate
    echo "  Waiting for deployments in $ns to terminate..."
    kubectl wait --for=delete deployment -n "$ns" -l "podgroup=$GROUP_NAME" --timeout=300s 2>/dev/null || true

    # Delete PNIs (Pod Network Instances) in batches
    # PNIs are created with names like: pod-network-instance-job0-0, pod-network-instance-job0-1-0, etc.
    echo "  Checking for PNIs to delete..."
    pni_names=$(kubectl get podnetworkinstances -n "$ns" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
    
    if [[ -n "$pni_names" ]]; then
        total_pnis=$(echo "$pni_names" | wc -l)
        echo "  Found $total_pnis PNIs to delete"
        
        # Batch PNIs for deletion (500 at a time)
        batch_pnis=""
        batch_pni_count=0
        pni_batch_num=1
        deleted_pnis=0

        while IFS= read -r pni_name; do
            # Handle empty lines
            if [[ -z "$pni_name" ]]; then
                continue
            fi

            batch_pnis="$batch_pnis $pni_name"
            batch_pni_count=$((batch_pni_count + 1))

            # If batch reaches target count, delete the batch
            if [[ $batch_pni_count -ge $CLEANUP_BATCH_SIZE ]]; then
                echo "  Deleting PNI batch $pni_batch_num ($batch_pni_count PNIs)..."
                retry_command 3 5 "kubectl delete podnetworkinstances -n $ns $batch_pnis --wait=false" || true
                deleted_pnis=$((deleted_pnis + batch_pni_count))
                
                # Reset batch
                batch_pnis=""
                batch_pni_count=0
                pni_batch_num=$((pni_batch_num + 1))
                
                # Small delay between batches
                sleep 1
            fi
        done <<< "$pni_names"

        # Delete remaining PNIs in the last batch
        if [[ -n "$batch_pnis" ]]; then
            echo "  Deleting final PNI batch $pni_batch_num ($batch_pni_count PNIs)..."
            retry_command 3 5 "kubectl delete podnetworkinstances -n $ns $batch_pnis --wait=false" || true
            deleted_pnis=$((deleted_pnis + batch_pni_count))
        fi

        echo "  Initiated deletion for $deleted_pnis PNIs across $pni_batch_num batches"
        
        # Wait for PNIs to be deleted
        echo "  Waiting for PNIs in $ns to terminate..."
        kubectl wait --for=delete podnetworkinstances -n "$ns" --all --timeout=300s 2>/dev/null || true
    else
        echo "  No PNIs found in namespace $ns"
    fi
    
    echo "  Namespace $ns cleanup complete"
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

# Always exit with 0 - subsequent scripts will cleanup the cluster/RG anyway
exit 0