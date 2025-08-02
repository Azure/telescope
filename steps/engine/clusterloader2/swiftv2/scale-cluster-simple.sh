#!/bin/bash
set -euo pipefail
set -x

# Simplified AKS Nodepool Scaling Script
# Focuses on scaling and then repairing failed VMs
#
# Required Environment Variables:
# - REGION: Azure region where the AKS cluster is located
# - ROLE: Role tag for resource identification
# - NODES_PER_NODEPOOL: Target node count per nodepool
# - RUN_ID: Run identifier tag for resource filtering

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

# =============================================================================
# SIMPLIFIED SCALING AND VM REPAIR
# =============================================================================

# Scale nodepool with basic timeout
function scale_nodepool() {
    local cluster_name=$1
    local nodepool=$2
    local resource_group=$3
    local target_count=$4
    
    log_info "Scaling nodepool '$nodepool' to $target_count nodes..."
    
    # Scale with 20-minute timeout
    if timeout 1200 az aks nodepool scale \
        --cluster-name "$cluster_name" \
        --name "$nodepool" \
        --resource-group "$resource_group" \
        --node-count "$target_count"; then
        log_info "Successfully scaled nodepool '$nodepool' to $target_count nodes"
        return 0
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            log_warning "Scale operation timed out after 20 minutes for nodepool '$nodepool'"
        else
            log_warning "Scale operation failed with exit code $exit_code for nodepool '$nodepool'"
        fi
        return $exit_code
    fi
}

# List all VMs in a nodepool and their status
function list_vm_status() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_info "Checking VM status for nodepool '$nodepool'..."
    
    # Get node resource group
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    # Find VMSS for this nodepool
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -n "$vmss_name" ]; then
        log_info "Found VMSS: '$vmss_name' for nodepool '$nodepool'"
        
        # List all VM instances with their status
        log_info "VM instance status for nodepool '$nodepool':"
        az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output table 2>/dev/null || log_warning "Unable to retrieve VMSS status"
        
        # Return VMSS info for repair operations
        echo "$vmss_name:$node_rg"
    else
        log_warning "No VMSS found for nodepool '$nodepool'"
        echo ":"
    fi
}

# Repair failed VMs by reimaging them
function repair_failed_vms() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3
    
    if [ -z "$vmss_name" ] || [ -z "$node_rg" ]; then
        log_info "No VMSS information available for repair"
        return 0
    fi
    
    log_info "Identifying failed VMs in nodepool '$nodepool'..."
    
    # Get list of failed instance IDs
    local failed_instances
    failed_instances=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed'].instanceId" \
        --output tsv 2>/dev/null || echo "")
    
    if [ -z "$failed_instances" ]; then
        log_info "No failed VMs found in nodepool '$nodepool'"
        return 0
    fi
    
    log_info "Found failed VM instances: $failed_instances"
    
    # Reimage each failed instance
    for instance_id in $failed_instances; do
        if [ -n "$instance_id" ]; then
            log_info "Reimaging VM instance '$instance_id' in VMSS '$vmss_name'..."
            
            # Reimage with timeout (don't wait for completion)
            timeout 300 az vmss reimage \
                --name "$vmss_name" \
                --resource-group "$node_rg" \
                --instance-id "$instance_id" \
                --no-wait 2>/dev/null || \
                log_warning "Reimage command failed or timed out for instance '$instance_id'"
        fi
    done
    
    log_info "Reimage operations initiated for all failed instances"
}

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
    
    log_info "Starting simplified AKS nodepool scaling operation"
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
    
    # Process each nodepool
    log_info "Processing $(echo "$usernodepools" | wc -w) nodepool(s)..."
    for nodepool in $usernodepools; do
        log_info "=== Processing nodepool: '$nodepool' ==="
        
        # Get current node count
        local current_nodes
        current_nodes=$(get_nodepool_count "$aks_name" "$nodepool" "$aks_rg")
        log_info "Current node count for nodepool '$nodepool': $current_nodes"
        
        # Scale if needed
        if [ "$current_nodes" != "$NODES_PER_NODEPOOL" ]; then
            log_info "Scaling nodepool '$nodepool': $current_nodes → $NODES_PER_NODEPOOL"
            scale_nodepool "$aks_name" "$nodepool" "$aks_rg" "$NODES_PER_NODEPOOL"
        else
            log_info "Nodepool '$nodepool' already at target size ($NODES_PER_NODEPOOL)"
        fi
        
        # Wait a moment for scale operation to stabilize
        log_info "Waiting 60 seconds for scale operation to stabilize..."
        sleep 60
        
        # List VM status and get VMSS info
        local vmss_info
        vmss_info=$(list_vm_status "$nodepool" "$aks_name" "$aks_rg")
        IFS=':' read -r vmss_name node_rg <<< "$vmss_info"
        
        # Repair any failed VMs
        repair_failed_vms "$vmss_name" "$node_rg" "$nodepool"
        
        log_info "Completed processing nodepool '$nodepool'"
    done
    
    log_info "All nodepool operations completed"
}

# Execute main function
main "$@"
