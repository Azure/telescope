#!/bin/bash
set -euo pipefail
set -x

# AKS Nodepool Scaling Script
# Scales AKS nodepools with robust error handling and VM failure recovery
# 
# Required Environment Variables:
# - REGION: Azure region where the AKS cluster is located
# - ROLE: Role tag for resource identification  
# - NODES_PER_NODEPOOL: Target node count per nodepool
# - RUN_ID: Run identifier tag for resource filtering

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"
source "$SCRIPT_DIR/vm-recovery.sh"

# =============================================================================
# SCALING OPERATIONS
# =============================================================================

# Scale a single nodepool with timeout and background monitoring
function scale_nodepool_with_timeout() {
    local cluster_name=$1
    local nodepool=$2
    local resource_group=$3
    local target_count=$4
    local operation_name=$5
    
    log_info "$operation_name nodepool '$nodepool' to $target_count nodes..."
    
    # Start background monitoring for long-running operations
    (
        sleep 900  # Wait 15 minutes
        log_warning "Scale operation running 15+ minutes for nodepool '$nodepool' - possible Azure infrastructure issues"
        sleep 900  # Wait another 15 minutes  
        log_warning "Scale operation running 30+ minutes for nodepool '$nodepool' - will timeout soon"
    ) &
    local monitor_pid=$!

    # Execute scale operation with 30-minute timeout
    if timeout 1800 az aks nodepool scale \
        --cluster-name "$cluster_name" \
        --name "$nodepool" \
        --resource-group "$resource_group" \
        --node-count "$target_count"; then
        
        # Kill background monitor on success
        kill $monitor_pid 2>/dev/null || true
        wait $monitor_pid 2>/dev/null || true
        log_info "Nodepool '$nodepool' scaled successfully to $target_count nodes"
        return 0
    else
        local exit_code=$?
        
        # Kill background monitor on failure
        kill $monitor_pid 2>/dev/null || true
        wait $monitor_pid 2>/dev/null || true
        
        if [ $exit_code -eq 124 ]; then
            log_warning "Scale operation timed out after 30 minutes for nodepool '$nodepool'"
        else
            log_warning "Scale operation failed with exit code $exit_code for nodepool '$nodepool'"
        fi
        return $exit_code
    fi
}

# Orchestrate nodepool scaling with retry logic and VM recovery
function scale_nodepool() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    local current_count=$4
    local target_count=$5
    local failed_vms=$6
    local vmss_name=$7
    local node_rg=$8
    
    # Configuration for retry attempts
    local max_attempts=3  # Maximum retry attempts
    log_info "Starting scale operation for nodepool '$nodepool': $current_count → $target_count nodes"
    
    # Handle failed VMs when target count matches current count
    if [ "$current_count" = "$target_count" ] && [ "$failed_vms" -gt 0 ]; then
        log_info "Using scale-down-then-scale-up strategy to recover $failed_vms failed VMs..."
        
        # Calculate temporary scale-down target
        local temp_scale_down=$((current_count - 1))
        if [ $temp_scale_down -lt 1 ]; then
            temp_scale_down=1
        fi
        
        # Step 1: Scale down to force VM refresh
        log_info "Step 1: Scaling down nodepool '$nodepool' to $temp_scale_down nodes..."
        for i in $(seq 1 $max_attempts); do
            log_info "Scale down attempt $i/$max_attempts for nodepool '$nodepool'..."
            
            if scale_nodepool_with_timeout "$cluster_name" "$nodepool" "$resource_group" "$temp_scale_down" "Scaling down"; then
                break
            else
                if [ $i -lt $max_attempts ]; then
                    log_info "Scale down failed, retrying in 60 seconds... (Attempt $i/$max_attempts)"
                    sleep 60
                else
                    log_warning "Failed to scale down nodepool '$nodepool' after $max_attempts attempts, proceeding with direct scale"
                fi
            fi
        done
        
        # Wait for scale down to complete
        log_info "Waiting for scale down to complete..."
        sleep 90
    fi

    # Step 2: Scale to target count
    log_info "Scaling nodepool '$nodepool' to target: $target_count nodes..."
    for i in $(seq 1 $max_attempts); do
        log_info "Scale up attempt $i/$max_attempts for nodepool '$nodepool'..."
        
        if scale_nodepool_with_timeout "$cluster_name" "$nodepool" "$resource_group" "$target_count" "Scaling up"; then
            log_info "Successfully scaled nodepool '$nodepool' to $target_count nodes"
            return 0
        else
            if [ $i -lt $max_attempts ]; then
                log_info "Scale up failed, retrying in 60 seconds... (Attempt $i/$max_attempts)"
                sleep 60
                
                # Attempt VM cleanup on retry attempts
                if [ $i -gt 1 ] && [ -n "$vmss_name" ] && [ -n "$node_rg" ]; then
                    cleanup_failed_vms "$vmss_name" "$node_rg" "$nodepool" "$i"
                fi
            fi
        fi
    done
    
    # All attempts failed
    log_error "Failed to scale nodepool '$nodepool' after $max_attempts attempts (~60 minutes total)"
    log_error "This likely indicates persistent Azure infrastructure issues"
    exit 1
}

# =============================================================================
# NODE READINESS VERIFICATION
# =============================================================================

# Verify that all nodes in a nodepool are ready in Kubernetes
function verify_node_readiness() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    local expected_nodes=$4
    
    # Get current nodepool count to validate
    local current_count
    current_count=$(get_nodepool_count "$cluster_name" "$nodepool" "$resource_group")
    
    # Skip verification if nodepool wasn't scaled to target
    if [ "$current_count" != "$expected_nodes" ]; then
        log_info "Skipping readiness check for nodepool '$nodepool' (current: $current_count, expected: $expected_nodes)"
        return 0
    fi
    
    log_info "Verifying node readiness for nodepool '$nodepool' ($expected_nodes nodes)..."
    
    # Calculate dynamic timeout based on node count
    local node_readiness_timeout=$((expected_nodes * 15))  # 15 seconds per node
    
    # Apply minimum and maximum timeout bounds
    if [ $node_readiness_timeout -lt 480 ]; then
        node_readiness_timeout=480  # 8 minutes minimum
    elif [ $node_readiness_timeout -gt 900 ]; then
        node_readiness_timeout=900  # 15 minutes maximum
    fi
    
    local RETRY_INTERVAL=30  # Check every 30 seconds
    local elapsed=0
    local consecutive_failures=0
    
    # Poll for node readiness
    while [ $elapsed -lt $node_readiness_timeout ]; do
        # Query node status for this nodepool
        local READY_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | grep " Ready " | wc -l || echo 0)
        local NOT_READY_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | grep " NotReady " | wc -l || echo 0)
        local TOTAL_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | wc -l || echo 0)
        
        log_info "Node readiness for '$nodepool': $READY_NODES ready, $NOT_READY_NODES not ready, $TOTAL_NODES total (target: $expected_nodes, elapsed: ${elapsed}s)"
        
        # Success condition: all expected nodes are ready
        if [ "$READY_NODES" -eq "$expected_nodes" ] && [ "$READY_NODES" -gt 0 ]; then
            log_info "All $READY_NODES nodes in nodepool '$nodepool' are ready"
            return 0
        fi
        
        # Handle different scenarios
        if [ "$TOTAL_NODES" -lt "$expected_nodes" ]; then
            log_info "Waiting for provisioning: $TOTAL_NODES/$expected_nodes nodes visible in Kubernetes"
            consecutive_failures=0
        elif [ "$READY_NODES" -eq 0 ] && [ $elapsed -gt 300 ]; then
            consecutive_failures=$((consecutive_failures + 1))
            log_info "No ready nodes after 5+ minutes, consecutive failures: $consecutive_failures"
            
            # Diagnose persistent issues
            if [ $consecutive_failures -ge 3 ]; then
                diagnose_node_issues "$nodepool" "$cluster_name" "$resource_group"
            fi
        else
            log_info "Node readiness progressing: $READY_NODES/$expected_nodes ready"
            consecutive_failures=0
        fi
        
        # Show detailed node status after 4 minutes for debugging
        if [ $elapsed -gt 240 ] && [ "$NOT_READY_NODES" -gt 0 ]; then
            log_info "Checking node conditions after 4 minutes..."
            kubectl get nodes -l agentpool="$nodepool" \
                -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,REASON:.status.conditions[-1].reason \
                2>/dev/null || true
        fi
        
        sleep $RETRY_INTERVAL
        elapsed=$((elapsed + RETRY_INTERVAL))
    done
    
    # Timeout reached - gather diagnostic information and fail
    handle_readiness_timeout "$nodepool" "$cluster_name" "$resource_group"
}

# Diagnose node readiness issues by checking VMSS status
function diagnose_node_issues() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_warning "Persistent node readiness issues detected for nodepool '$nodepool', checking VMSS status..."
    
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -n "$vmss_name" ]; then
        show_vmss_status "$vmss_name" "$node_rg" "diagnostic check"
    fi
}

# Handle node readiness timeout with comprehensive diagnostics
function handle_readiness_timeout() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_error "Timeout waiting for nodes in nodepool '$nodepool' to be ready"
    
    # Show final node status
    log_info "Final node status:"
    kubectl get nodes -l agentpool="$nodepool" -o wide 2>/dev/null || echo "Unable to get node status"
    
    # Show VMSS status for additional debugging
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -n "$vmss_name" ]; then
        show_vmss_status "$vmss_name" "$node_rg" "timeout diagnostics"
    fi
    
    exit 1
}

# =============================================================================
# MAIN ORCHESTRATION
# =============================================================================

# Validate required environment variables
function validate_environment() {
    local missing_vars=""
    
    [ -z "${REGION:-}" ] && missing_vars="$missing_vars REGION"
    [ -z "${ROLE:-}" ] && missing_vars="$missing_vars ROLE"
    [ -z "${NODES_PER_NODEPOOL:-}" ] && missing_vars="$missing_vars NODES_PER_NODEPOOL"
    [ -z "${RUN_ID:-}" ] && missing_vars="$missing_vars RUN_ID"
    
    if [ -n "$missing_vars" ]; then
        log_error "Missing required environment variables:$missing_vars"
        exit 1
    fi
}

# Main execution function
function main() {
    # Validate environment
    validate_environment
    
    log_info "Starting AKS nodepool scaling operation"
    log_info "  Region: $REGION"
    log_info "  Role: $ROLE" 
    log_info "  Target nodes per nodepool: $NODES_PER_NODEPOOL"
    log_info "  Run ID: $RUN_ID"
    
    # Discover and connect to AKS cluster
    find_aks_cluster "$REGION" "$ROLE"
    
    # Get user nodepools to scale
    local usernodepools
    usernodepools=$(get_user_nodepools "$aks_name" "$aks_rg")
    if [ $? -ne 0 ]; then
        log_info "No user nodepools found to scale, exiting"
        exit 0
    fi
    
    # Scale each nodepool
    log_info "Processing $(echo "$usernodepools" | wc -w) nodepool(s) for scaling..."
    for nodepool in $usernodepools; do
        log_info "=== Processing nodepool: '$nodepool' ==="
        
        # Get current node count
        local current_nodes
        current_nodes=$(get_nodepool_count "$aks_name" "$nodepool" "$aks_rg")
        log_info "Current node count for nodepool '$nodepool': $current_nodes"
        
        # Check for failed VMs and get recovery information
        local vm_info
        vm_info=$(check_failed_vms "$nodepool" "$aks_name" "$aks_rg")
        IFS=':' read -r failed_vms vmss_name node_rg <<< "$vm_info"
        
        # Determine if scaling is needed
        local needs_scaling=false
        if [ "$current_nodes" != "$NODES_PER_NODEPOOL" ]; then
            needs_scaling=true
            log_info "Nodepool '$nodepool' needs scaling: $current_nodes → $NODES_PER_NODEPOOL"
        elif [ "$failed_vms" -gt 0 ]; then
            needs_scaling=true
            log_info "Nodepool '$nodepool' has $failed_vms failed VMs, forcing scale operation for recovery"
        fi

        # Execute scaling if needed
        if [ "$needs_scaling" = true ]; then
            scale_nodepool "$nodepool" "$aks_name" "$aks_rg" "$current_nodes" "$NODES_PER_NODEPOOL" "$failed_vms" "$vmss_name" "$node_rg"
        else
            log_info "Nodepool '$nodepool' already at target size ($NODES_PER_NODEPOOL) with no failed VMs"
        fi
    done

    # Verify all nodes are ready after scaling
    log_info "=== Verifying node readiness across all nodepools ==="
    for nodepool in $usernodepools; do
        verify_node_readiness "$nodepool" "$aks_name" "$aks_rg" "$NODES_PER_NODEPOOL"
    done

    log_info "All nodepool scaling and readiness verification completed successfully"
}

# Execute main function with all arguments
main "$@"
