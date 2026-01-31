#!/bin/bash

# AKS Utilities Library
# Contains common functions for AKS cluster management, logging, and nodepool operations

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

# Source common library for cancellation handling and shared functions
source "${REPO_ROOT}/swiftv2kubeobjects/lib/common.sh"

# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================

# Log informational messages
function log_info() {
    echo "[INFO] $1"
}

# Log warning messages for Azure DevOps
function log_warning() {
    echo "##vso[task.logissue type=warning;] $1"
}

# Log error messages for Azure DevOps
function log_error() {
    echo "##vso[task.logissue type=error;] $1"
}

# =============================================================================
# AKS CLUSTER DISCOVERY
# =============================================================================

# Find AKS cluster by region and role tags
# Sets global variables: aks_name, aks_rg
function find_aks_cluster() {
    local region=$1
    local role=$2
    
    # Use RESOURCE_GROUP_NAME pipeline variable (set by provision-resources.yml)
    # This is the single source of truth for resource group naming.
    if [ -z "${RESOURCE_GROUP_NAME:-}" ]; then
        log_error "RESOURCE_GROUP_NAME not set. This should be set by provision-resources.yml"
        exit 1
    fi
    local cluster_run_id="$RESOURCE_GROUP_NAME"
    log_info "Using RESOURCE_GROUP_NAME: $cluster_run_id"
    
    log_info "Finding AKS cluster with role '$role' in region '$region'..."
    log_info "Using run_id tag: $cluster_run_id"
    
    # Query for AKS cluster name matching tags
    aks_name=$(az resource list \
        --resource-type Microsoft.ContainerService/managedClusters \
        --location "$region" \
        --query "[?(tags.run_id == '$cluster_run_id' && tags.role == '$role')].name" \
        --output tsv)

    # Query for AKS cluster resource group matching tags
    aks_rg=$(az resource list \
        --resource-type Microsoft.ContainerService/managedClusters \
        --location "$region" \
        --query "[?(tags.run_id == '$cluster_run_id' && tags.role == '$role')].resourceGroup" \
        --output tsv)

    # Validate cluster was found
    if [ -z "$aks_name" ]; then
        log_error "No AKS cluster found with role '$role' and run_id '$cluster_run_id' in region '$region'"
        exit 1
    fi
    
    log_info "Found AKS cluster: '$aks_name' in resource group: '$aks_rg'"
    
    # Get kubectl credentials for the cluster
    az aks get-credentials --name "$aks_name" --resource-group "$aks_rg"
}

# =============================================================================
# NODEPOOL MANAGEMENT
# =============================================================================

# Get list of user nodepools (excludes system and test nodepools)
function get_user_nodepools() {
    local cluster_name=$1
    local resource_group=$2
    
    log_info "Discovering user nodepools for cluster '$cluster_name'..." >&2
    
    # Get all nodepools as JSON
    local nodepools
    nodepools=$(az aks nodepool list \
        --cluster-name "$cluster_name" \
        --resource-group "$resource_group" \
        --output json)
    
    # Filter for user nodepools (exclude system, prometheus, devtest, and buffer pools)
    local usernodepools
    usernodepools=$(echo "$nodepools" | jq -r '
        .[] | 
        select(
            .mode == "User" and 
            .name != "promnodepool" and 
            (.name | contains("devtest") | not) and
            (.name | contains("buffer") | not)
        ) | 
        .name'
    )
    
    if [ -z "$usernodepools" ]; then
        log_warning "No user nodepools found to scale" >&2
        return 1
    fi
    
    log_info "Found user nodepools: $(echo "$usernodepools" | tr '\n' ' ')" >&2
    echo "$usernodepools"
}

# Get current node count for a nodepool
function get_nodepool_count() {
    local cluster_name=$1
    local nodepool=$2
    local resource_group=$3
    
    az aks nodepool show \
        --cluster-name "$cluster_name" \
        --name "$nodepool" \
        --resource-group "$resource_group" \
        --query 'count' \
        --output tsv
}

# =============================================================================
# AZURE RESOURCE QUERIES
# =============================================================================

# Get the node resource group for an AKS cluster
function get_node_resource_group() {
    local cluster_name=$1
    local resource_group=$2
    
    az aks show \
        --name "$cluster_name" \
        --resource-group "$resource_group" \
        --query nodeResourceGroup \
        --output tsv
}

# Find VMSS name for a nodepool
function get_vmss_name() {
    local nodepool=$1
    local node_rg=$2
    
    az vmss list \
        --resource-group "$node_rg" \
        --query "[?contains(name, '${nodepool}')].name" \
        --output tsv | head -1
}

# =============================================================================
# NODE LABELING
# =============================================================================

# Label nodes with retry mechanism for robustness
# Usage: label_nodes_with_retry "<label_key>=<label_value>" node1 node2 node3 ...
# Returns: 0 on success (all nodes labeled), 1 on partial/complete failure
function label_nodes_with_retry() {
    local label=$1
    shift
    local nodes=("$@")
    local max_retries=3
    local retry_delay=30  # seconds between retries
    
    if [ ${#nodes[@]} -eq 0 ]; then
        log_warning "No nodes provided to label_nodes_with_retry"
        return 1
    fi
    
    log_info "Labeling ${#nodes[@]} node(s) with $label (max retries: $max_retries)..."
    
    # Attempt to label nodes with retries
    local labeled_count=0
    local -a failed_nodes=()
    
    for attempt in $(seq 1 $max_retries); do
        local attempt_labeled=0
        local attempt_failed=0
        local -a newly_failed=()
        
        # On first attempt, try all nodes. On subsequent attempts, retry only failed nodes.
        local -a current_nodes
        if [ $attempt -eq 1 ]; then
            current_nodes=("${nodes[@]}")
        else
            current_nodes=("${failed_nodes[@]}")
            log_info "Retrying failed nodes (attempt $attempt/$max_retries)..."
            sleep $retry_delay
        fi
        
        for node in "${current_nodes[@]}"; do
            if kubectl label node "$node" "$label" --overwrite >/dev/null 2>&1; then
                attempt_labeled=$((attempt_labeled + 1))
            else
                attempt_failed=$((attempt_failed + 1))
                newly_failed+=("$node")
            fi
        done
        
        # Update total labeled count
        if [ $attempt -eq 1 ]; then
            labeled_count=$attempt_labeled
        else
            # On retry, calculate how many previously failed nodes succeeded
            local recovered=$((${#failed_nodes[@]} - ${#newly_failed[@]}))
            labeled_count=$((labeled_count + recovered))
        fi
        
        # Update failed nodes list for next retry
        failed_nodes=("${newly_failed[@]}")
        
        if [ $attempt -eq 1 ]; then
            log_info "Attempt $attempt complete: $attempt_labeled successful, $attempt_failed failed"
        else
            log_info "Attempt $attempt complete: recovered $((${#current_nodes[@]} - ${#newly_failed[@]})), still failing ${#newly_failed[@]}"
        fi
        
        # If all nodes are labeled, we're done
        if [ ${#failed_nodes[@]} -eq 0 ]; then
            log_info "Successfully labeled all ${#nodes[@]} node(s) with $label"
            return 0
        fi
        
        # If this was the last attempt, log final status
        if [ $attempt -eq $max_retries ]; then
            log_warning "Failed to label ${#failed_nodes[@]} node(s) after $max_retries attempts"
            log_warning "Failed nodes: ${failed_nodes[*]}"
        fi
    done
    
    local final_failed_count=${#failed_nodes[@]}
    log_warning "Labeling completed with failures: $labeled_count successful, $final_failed_count failed (after $max_retries attempts)"
    
    if [ "$labeled_count" -eq 0 ]; then
        log_error "Failed to label any nodes"
        return 1
    fi
    
    # Partial success - return failure but log success count
    log_info "Partially successful: labeled $labeled_count/${#nodes[@]} nodes"
    return 1
}

# Verify that nodes have specific labels visible to the API server
# Useful after labeling to ensure labels have propagated before dependent operations
# Usage: verify_node_labels <expected_count> <max_wait_seconds> <label_selector>
# Example: verify_node_labels 100 60 "swiftv2slo=true,image-prepull-batch-0=true"
# Returns: 0 if expected count reached, 1 if timeout
# Sets: VERIFIED_NODE_COUNT with actual count of matching nodes
function verify_node_labels() {
    local expected_count=$1
    local max_wait=${2:-60}  # Default 60 seconds
    local label_selector=$3
    
    if [ -z "$label_selector" ]; then
        log_error "verify_node_labels: label_selector is required"
        return 1
    fi
    
    log_info "Verifying node labels: expecting $expected_count nodes with selector '$label_selector'..."
    
    local verify_interval=5
    local verify_elapsed=0
    VERIFIED_NODE_COUNT=0
    
    while [ $verify_elapsed -lt $max_wait ]; do
        VERIFIED_NODE_COUNT=$(kubectl get nodes -l "$label_selector" --no-headers 2>/dev/null | wc -l | tr -d ' ')
        
        if [ "$VERIFIED_NODE_COUNT" -ge "$expected_count" ]; then
            log_info "  ✓ Verified: $VERIFIED_NODE_COUNT nodes match selector (expected: $expected_count)"
            return 0
        fi
        
        if [ $verify_elapsed -eq 0 ]; then
            log_info "  Waiting for label propagation: $VERIFIED_NODE_COUNT/$expected_count visible..."
        elif [ $((verify_elapsed % 15)) -eq 0 ]; then
            log_info "  Label propagation progress: $VERIFIED_NODE_COUNT/$expected_count visible (${verify_elapsed}s)"
        fi
        
        sleep $verify_interval
        verify_elapsed=$((verify_elapsed + verify_interval))
    done
    
    log_warning "  Label verification timeout: only $VERIFIED_NODE_COUNT/$expected_count nodes visible after ${max_wait}s"
    return 1
}

# Batch label nodes in parallel for performance
# Usage: batch_label_nodes "<label_key>=<label_value>" node1 node2 node3 ...
# Returns: 0 on success, 1 on failure
function batch_label_nodes() {
    local label=$1
    shift
    local nodes=("$@")
    local parallelism=50
    
    if [ ${#nodes[@]} -eq 0 ]; then
        log_warning "No nodes provided to batch_label_nodes"
        return 1
    fi
    
    log_info "Batch labeling ${#nodes[@]} node(s) with $label (parallelism: $parallelism)..."
    
    # Use xargs for parallel execution
    local failed_count=0
    local labeled_count=0
    
    for node in "${nodes[@]}"; do
        if kubectl label node "$node" "$label" --overwrite 2>&1 | grep -q "labeled\|not found"; then
            labeled_count=$((labeled_count + 1))
        else
            failed_count=$((failed_count + 1))
        fi
    done &
    wait
    
    # Use the more robust retry-based approach instead
    if ! label_nodes_with_retry "$label" "${nodes[@]}"; then
        return 1
    fi
    
    return 0
}
