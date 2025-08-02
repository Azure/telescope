#!/bin/bash
set -euo pipefail
set -x

# VM Status and Repair Script
# Lists all VMs in nodepools and repairs failed ones
#
# Required Environment Variables:
# - REGION: Azure region where the AKS cluster is located
# - ROLE: Role tag for resource identification
# - RUN_ID: Run identifier tag for resource filtering

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

# =============================================================================
# VM STATUS AND REPAIR FUNCTIONS
# =============================================================================

# List detailed VM status for a nodepool
function show_detailed_vm_status() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_info "=== Detailed VM Status for nodepool '$nodepool' ==="
    
    # Get node resource group
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    # Find VMSS for this nodepool
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -n "$vmss_name" ]; then
        log_info "VMSS Name: $vmss_name"
        log_info "Node Resource Group: $node_rg"
        
        # Show basic instance information
        log_info "VM Instances Summary:"
        az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output table 2>/dev/null || log_warning "Unable to retrieve basic VMSS status"
        
        # Show detailed status for failed VMs
        local failed_instances
        failed_instances=$(az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[?provisioningState=='Failed'].instanceId" \
            --output tsv 2>/dev/null || echo "")
        
        if [ -n "$failed_instances" ]; then
            log_warning "Found failed VM instances: $failed_instances"
            
            # Show detailed information for failed instances
            for instance_id in $failed_instances; do
                log_info "Detailed status for failed instance $instance_id:"
                az vmss get-instance-view \
                    --name "$vmss_name" \
                    --resource-group "$node_rg" \
                    --instance-id "$instance_id" \
                    --query "{InstanceId:'$instance_id',ProvisioningState:provisioningState,Statuses:statuses[].{Code:code,DisplayStatus:displayStatus,Message:message}}" \
                    --output json 2>/dev/null || log_warning "Unable to get detailed status for instance $instance_id"
            done
        else
            log_info "No failed VMs found in nodepool '$nodepool'"
        fi
        
        # Show Kubernetes node status for comparison
        log_info "Kubernetes nodes status for nodepool '$nodepool':"
        kubectl get nodes -l agentpool="$nodepool" \
            -o custom-columns="NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[?(@.type=='Ready')].status" \
            2>/dev/null || log_warning "Unable to get Kubernetes node status"
        
        return 0
    else
        log_warning "No VMSS found for nodepool '$nodepool'"
        return 1
    fi
}

# Repair all failed VMs in a nodepool
function repair_nodepool_vms() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_info "=== Repairing failed VMs in nodepool '$nodepool' ==="
    
    # Get node resource group
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    # Find VMSS for this nodepool
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -z "$vmss_name" ]; then
        log_warning "No VMSS found for nodepool '$nodepool', skipping repair"
        return 1
    fi
    
    # Get list of failed instance IDs
    local failed_instances
    failed_instances=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed'].instanceId" \
        --output tsv 2>/dev/null || echo "")
    
    if [ -z "$failed_instances" ]; then
        log_info "No failed VMs found in nodepool '$nodepool' - no repair needed"
        return 0
    fi
    
    log_info "Starting repair for failed instances: $failed_instances"
    
    # Reimage each failed instance
    for instance_id in $failed_instances; do
        if [ -n "$instance_id" ]; then
            log_info "Initiating reimage for VM instance '$instance_id'..."
            
            # Use reimage with no-wait to avoid blocking
            if az vmss reimage \
                --name "$vmss_name" \
                --resource-group "$node_rg" \
                --instance-id "$instance_id" \
                --no-wait 2>/dev/null; then
                log_info "Reimage command successful for instance '$instance_id'"
            else
                log_warning "Reimage command failed for instance '$instance_id'"
            fi
        fi
    done
    
    log_info "Repair operations initiated for all failed VMs in nodepool '$nodepool'"
    log_info "Note: Reimage operations are running in background and may take several minutes to complete"
}

# Validate required environment variables
function validate_environment() {
    local missing_vars=""
    
    [ -z "${REGION:-}" ] && missing_vars="$missing_vars REGION"
    [ -z "${ROLE:-}" ] && missing_vars="$missing_vars ROLE"
    [ -z "${RUN_ID:-}" ] && missing_vars="$missing_vars RUN_ID"
    
    if [ -n "$missing_vars" ]; then
        log_error "Missing required environment variables:$missing_vars"
        exit 1
    fi
}

# Main execution function
function main() {
    local action="${1:-status}"  # Default action is to show status
    
    # Validate environment
    validate_environment
    
    log_info "VM Status and Repair Tool"
    log_info "  Region: $REGION"
    log_info "  Role: $ROLE"
    log_info "  Run ID: $RUN_ID"
    log_info "  Action: $action"
    
    # Discover and connect to AKS cluster
    find_aks_cluster "$REGION" "$ROLE"
    
    # Get user nodepools
    local usernodepools
    usernodepools=$(get_user_nodepools "$aks_name" "$aks_rg")
    if [ $? -ne 0 ]; then
        log_info "No user nodepools found, exiting"
        exit 0
    fi
    
    # Process each nodepool based on action
    case "$action" in
        "status")
            log_info "Showing VM status for all nodepools..."
            for nodepool in $usernodepools; do
                show_detailed_vm_status "$nodepool" "$aks_name" "$aks_rg"
                echo  # Add spacing between nodepools
            done
            ;;
        "repair")
            log_info "Repairing failed VMs in all nodepools..."
            for nodepool in $usernodepools; do
                repair_nodepool_vms "$nodepool" "$aks_name" "$aks_rg"
                echo  # Add spacing between nodepools
            done
            ;;
        "both"|"all")
            log_info "Showing status and repairing failed VMs..."
            for nodepool in $usernodepools; do
                show_detailed_vm_status "$nodepool" "$aks_name" "$aks_rg"
                repair_nodepool_vms "$nodepool" "$aks_name" "$aks_rg"
                echo  # Add spacing between nodepools
            done
            ;;
        *)
            log_error "Unknown action: $action"
            log_info "Usage: $0 [status|repair|both]"
            log_info "  status: Show detailed VM status (default)"
            log_info "  repair: Repair failed VMs"
            log_info "  both:   Show status and repair failed VMs"
            exit 1
            ;;
    esac
    
    log_info "VM operations completed"
}

# Execute main function with all arguments
main "$@"
