#!/bin/bash

# VM Recovery Library
# Contains functions for detecting and recovering failed VMs in VMSS nodepools

# Source the utilities library
source "$(dirname "${BASH_SOURCE[0]}")/aks-utils.sh"

# =============================================================================
# VM FAILURE DETECTION AND RECOVERY
# =============================================================================

# Check for failed VMs in a nodepool and attempt recovery
# Returns: "failed_vm_count:vmss_name:node_rg"
function check_failed_vms() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_info "Checking for failed VMs in nodepool '$nodepool'..."
    
    # Get node resource group
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    # Find VMSS for this nodepool
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    local failed_vms=0
    
    if [ -n "$vmss_name" ]; then
        log_info "Found VMSS: '$vmss_name' for nodepool '$nodepool'"
        
        # Count VMs in failed provisioning state
        failed_vms=$(az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[?provisioningState=='Failed' || instanceView.statuses[?code=='ProvisioningState/failed']] | length(@)" \
            --output tsv 2>/dev/null || echo 0)
        
        log_info "Found $failed_vms failed VMs in nodepool '$nodepool'"
        
        # Attempt to recover failed VMs
        if [ "$failed_vms" -gt 0 ]; then
            reimage_failed_vms "$vmss_name" "$node_rg" "$nodepool"
        fi
    else
        log_warning "No VMSS found for nodepool '$nodepool'"
    fi
    
    echo "$failed_vms:$vmss_name:$node_rg"
}

# Attempt to reimage failed VM instances
function reimage_failed_vms() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3
    
    log_info "Attempting to reimage failed VMs in nodepool '$nodepool'..."
    
    # Get list of failed instance IDs
    local failed_instance_ids
    failed_instance_ids=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed'].instanceId" \
        --output tsv 2>/dev/null || echo "")
    
    # Reimage each failed instance
    for instance_id in $failed_instance_ids; do
        if [ -n "$instance_id" ]; then
            log_info "Reimaging VM instance '$instance_id' in VMSS '$vmss_name'..."
            
            # Use timeout to prevent hanging operations (5 minutes max)
            timeout 300 az vmss reimage \
                --name "$vmss_name" \
                --resource-group "$node_rg" \
                --instance-id "$instance_id" \
                --no-wait 2>/dev/null || \
                log_warning "Reimage failed or timed out for instance '$instance_id'"
        fi
    done
    
    # Allow time for reimage operations to initialize
    if [ -n "$failed_instance_ids" ]; then
        log_info "Waiting 30 seconds for reimage operations to start..."
        sleep 30
    fi
}

# Clean up persistent failed VMs by deleting them
function cleanup_failed_vms() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3
    local attempt=$4
    
    log_info "Checking for persistent failed VMs after retry attempt $attempt for nodepool '$nodepool'..."
    
    # Find VMs that are still in failed state
    local persistent_failed
    persistent_failed=$(timeout 60 az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed'].instanceId" \
        --output tsv 2>/dev/null || echo "")
    
    # Delete persistent failed instances
    for instance_id in $persistent_failed; do
        if [ -n "$instance_id" ]; then
            log_info "Deleting persistent failed VM instance '$instance_id'..."
            
            # Use timeout to prevent hanging operations (5 minutes max)
            timeout 300 az vmss delete-instances \
                --name "$vmss_name" \
                --resource-group "$node_rg" \
                --instance-ids "$instance_id" \
                --no-wait 2>/dev/null || \
                log_warning "Delete failed or timed out for instance '$instance_id'"
        fi
    done
    
    # Allow time for delete operations to process
    if [ -n "$persistent_failed" ]; then
        log_info "Waiting 30 seconds for delete operations to process..."
        sleep 30
    fi
}

# =============================================================================
# VMSS STATUS REPORTING
# =============================================================================

# Display detailed VMSS instance status for debugging
function show_vmss_status() {
    local vmss_name=$1
    local node_rg=$2
    local context=$3
    
    if [ -n "$vmss_name" ]; then
        log_info "VMSS instances status ($context):"
        az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output table 2>/dev/null || echo "Unable to retrieve VMSS status"
    fi
}
