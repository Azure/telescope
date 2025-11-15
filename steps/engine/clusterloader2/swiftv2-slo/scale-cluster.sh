#!/bin/bash
set -euo pipefail
set -x

# Simplified AKS Nodepool Scaling Script
# Focuses on scaling and then repairing failed VMs
#
# Required Environment Variables:
# - REGION: Azure region where the AKS cluster is located
# - ROLE: Role tag for resource identification
# - NODE_COUNT: Target node count per nodepool
# - RUN_ID: Run identifier tag for resource filtering

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

# =============================================================================
# CANCELLATION HANDLING
# =============================================================================

# Global flag for cancellation detection
CANCELLED=false

# Signal handler for graceful shutdown
function handle_cancellation() {
    log_warning "Received cancellation signal (SIGTERM/SIGINT)"
    CANCELLED=true
    
    # Give processes a moment to clean up
    sleep 2
    
    log_error "Pipeline cancellation detected. Exiting gracefully..."
    exit 143  # Standard exit code for SIGTERM
}

# Set up signal traps for cancellation
trap handle_cancellation SIGTERM SIGINT

# Check if pipeline has been cancelled (Azure DevOps specific)
function check_cancellation() {
    if [ "$CANCELLED" = true ]; then
        log_warning "Cancellation detected, stopping current operation..."
        return 1
    fi
    
    # Check for Azure DevOps cancellation marker file (if exists)
    if [ -f "/tmp/pipeline_cancelled" ]; then
        log_warning "Pipeline cancellation marker detected"
        CANCELLED=true
        return 1
    fi
    
    return 0
}

# =============================================================================
# SIMPLIFIED SCALING AND VM REPAIR
# =============================================================================

# Calculate timeout based on node count
function get_scale_timeout() {
    local node_count=$1
    
    if [ "$node_count" -le 100 ]; then
        echo 900  # 15 minutes
    elif [ "$node_count" -le 200 ]; then
        echo 1200  # 20 minutes
    elif [ "$node_count" -le 500 ]; then
        echo 1800  # 30 minutes
    elif [ "$node_count" -le 750 ]; then
        echo 2700  # 45 minutes
    else
        echo 3600  # 60 minutes for 1000+ nodes
    fi
}

# Get actual VMSS instance count for a nodepool
function get_vmss_instance_count() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -z "$vmss_name" ]; then
        echo "0"
        return 1
    fi
    
    local instance_count
    instance_count=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "length([?provisioningState=='Succeeded'])" \
        --output tsv 2>/dev/null || echo "0")
    
    echo "$instance_count"
    return 0
}

# Scale nodepool with dynamic timeout and retries if VMs are not provisioned
function scale_nodepool() {
    local cluster_name=$1
    local nodepool=$2
    local resource_group=$3
    local target_count=$4
    local max_scale_retries=${MAX_SCALE_RETRIES:-3}  # Allow override via env var
    local retry_delay=60  # Wait 60 seconds between retries
    
    local scale_attempt=0
    local scale_success=false
    
    while [ $scale_attempt -lt $max_scale_retries ] && [ "$scale_success" = false ]; do
        scale_attempt=$((scale_attempt + 1))
        
        if [ $scale_attempt -gt 1 ]; then
            log_warning "Retry attempt $scale_attempt/$max_scale_retries for scaling nodepool '$nodepool'"
            log_info "Waiting $retry_delay seconds before retry..."
            sleep $retry_delay
        fi
        
        # Calculate timeout based on node count
        local timeout_seconds
        timeout_seconds=$(get_scale_timeout "$target_count")
        local timeout_minutes=$((timeout_seconds / 60))
        
        log_info "Scaling nodepool '$nodepool' to $target_count nodes (attempt $scale_attempt/$max_scale_retries, timeout: ${timeout_minutes} minutes)..."
        
        # Scale with dynamic timeout
        local scale_result=0
        if timeout "$timeout_seconds" az aks nodepool scale \
            --cluster-name "$cluster_name" \
            --name "$nodepool" \
            --resource-group "$resource_group" \
            --node-count "$target_count"; then
            log_info "Scale command completed for nodepool '$nodepool'"
        else
            scale_result=$?
            if [ $scale_result -eq 124 ]; then
                log_warning "Scale operation timed out after ${timeout_minutes} minutes for nodepool '$nodepool'"
            else
                log_warning "Scale operation failed with exit code $scale_result for nodepool '$nodepool'"
            fi
        fi
        
        # Wait for VMSS to stabilize
        log_info "Waiting 30 seconds for VMSS to stabilize..."
        sleep 30
        
        # Verify actual VMSS instance count
        log_info "Verifying actual VMSS instance count for nodepool '$nodepool'..."
        local actual_count
        actual_count=$(get_vmss_instance_count "$nodepool" "$cluster_name" "$resource_group")
        
        log_info "VMSS actual count: $actual_count, target: $target_count (attempt $scale_attempt/$max_scale_retries)"
        
        if [ "$actual_count" -eq "$target_count" ]; then
            log_info "Successfully scaled nodepool '$nodepool' to $target_count nodes (verified)"
            scale_success=true
            return 0
        elif [ "$actual_count" -gt 0 ] && [ "$actual_count" -ge $((target_count - 5)) ]; then
            log_warning "Nodepool '$nodepool' scaled to $actual_count/$target_count nodes (within tolerance)"
            scale_success=true
            return 0
        else
            log_warning "Scale incomplete for nodepool '$nodepool': got $actual_count/$target_count nodes (attempt $scale_attempt/$max_scale_retries)"
            
            # If this isn't the last retry, continue to next attempt
            if [ $scale_attempt -lt $max_scale_retries ]; then
                log_info "Will retry scaling operation..."
            fi
        fi
    done
    
    # All retries exhausted
    if [ "$scale_success" = false ]; then
        log_error "Failed to scale nodepool '$nodepool' to $target_count nodes after $max_scale_retries attempts"
        log_error "Final VMSS count: $(get_vmss_instance_count "$nodepool" "$cluster_name" "$resource_group")/$target_count"
        
        # Check if we should fail hard when exact count is required
        if [ "${PROVISION_BUFFER_NODES:-true}" = "false" ]; then
            log_error "PROVISION_BUFFER_NODES is false. Failing due to insufficient VMs."
            return 1
        else
            log_warning "PROVISION_BUFFER_NODES is true. Continuing to VM repair phase..."
            return 0  # Continue to VM repair instead of failing
        fi
    fi
    
    return 0
}

# List all VMs in a nodepool and their status
function list_vm_status() {
    local nodepool=$1
    local cluster_name=$2
    local resource_group=$3
    
    log_info "Checking VM status for nodepool '$nodepool'..." >&2
    
    # Get node resource group
    local node_rg
    node_rg=$(get_node_resource_group "$cluster_name" "$resource_group")
    
    # Find VMSS for this nodepool
    local vmss_name
    vmss_name=$(get_vmss_name "$nodepool" "$node_rg")
    
    if [ -n "$vmss_name" ]; then
        log_info "Found VMSS: '$vmss_name' for nodepool '$nodepool'" >&2
        
        # List all VM instances with their status
        log_info "VM instance status for nodepool '$nodepool':" >&2
        az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output table >&2 2>/dev/null || log_warning "Unable to retrieve VMSS status" >&2
        
        # Return VMSS info for repair operations
        echo "$vmss_name:$node_rg"
    else
        log_warning "No VMSS found for nodepool '$nodepool'" >&2
        echo ":"
    fi
}

# Delete failed VMs and wait for new ones to be provisioned
function repair_failed_vms() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3
    local max_retries=3
    local retry_delay=30
    
    if [ -z "$vmss_name" ] || [ -z "$node_rg" ]; then
        log_info "No VMSS information available for VM cleanup"
        return 0
    fi
    
    log_info "Identifying failed VMs in nodepool '$nodepool'..."
    
    # Get list of failed instance IDs (Failed state, OSProvisioningTimedOut, and other failure statuses)
    local all_failed_instances
    all_failed_instances=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed' || contains(to_string(instanceView.statuses[]), 'OSProvisioningTimedOut') || contains(to_string(instanceView.statuses[]), 'ProvisioningState/failed')].instanceId" \
        --output tsv 2>/dev/null | sort -u | grep -v '^$' || echo "")
    
    if [ -z "$all_failed_instances" ]; then
        log_info "No failed VMs found in nodepool '$nodepool'"
        return 0
    fi
    
    log_info "Found failed VM instances: $all_failed_instances"
    
    # Log detailed failure information for troubleshooting
    log_info "Checking detailed failure reasons..."
    az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[?provisioningState=='Failed'].{InstanceId:instanceId,ProvisioningState:provisioningState,Statuses:instanceView.statuses[?code=='ProvisioningState/failed/OSProvisioningTimedOut' || contains(code,'failed')].{Code:code,Message:message}}" \
        --output table 2>/dev/null || log_warning "Unable to retrieve detailed failure information"
    
    # Count the number of failed instances to track replacements
    local failed_count=0
    for instance_id in $all_failed_instances; do
        if [ -n "$instance_id" ]; then
            failed_count=$((failed_count + 1))
        fi
    done
    
    if [ $failed_count -eq 0 ]; then
        log_info "No valid failed instances to delete"
        return 0
    fi
    
    log_info "Deleting $failed_count failed VM instances to trigger replacement..."
    
    # Delete each failed instance with retry logic
    local deleted_instances=""
    for instance_id in $all_failed_instances; do
        if [ -n "$instance_id" ]; then
            local retry_count=0
            local delete_success=false
            
            while [ $retry_count -lt $max_retries ] && [ "$delete_success" = false ]; do
                retry_count=$((retry_count + 1))
                
                if [ $retry_count -gt 1 ]; then
                    log_info "Retry attempt $retry_count/$max_retries for deleting VM instance '$instance_id'"
                    log_info "Waiting $retry_delay seconds before retry..."
                    sleep $retry_delay
                else
                    log_info "Deleting failed VM instance '$instance_id' from VMSS '$vmss_name' (attempt $retry_count/$max_retries)..."
                fi
                
                # Delete instance with timeout
                if timeout 180 az vmss delete-instances \
                    --name "$vmss_name" \
                    --resource-group "$node_rg" \
                    --instance-ids "$instance_id" \
                    --no-wait 2>/dev/null; then
                    log_info "Successfully initiated deletion for VM instance '$instance_id'"
                    delete_success=true
                    deleted_instances="$deleted_instances $instance_id"
                else
                    local exit_code=$?
                    if [ $retry_count -lt $max_retries ]; then
                        log_warning "Delete attempt $retry_count failed for instance '$instance_id' (exit code: $exit_code), will retry..."
                    else
                        log_warning "All $max_retries delete attempts failed for instance '$instance_id' (exit code: $exit_code)"
                    fi
                fi
            done
            
            if [ "$delete_success" = false ]; then
                log_warning "Failed to delete VM instance '$instance_id' after $max_retries attempts, continuing with other instances..."
            fi
        fi
    done
    
    if [ -n "$deleted_instances" ]; then
        log_info "Successfully initiated deletion for instances:$deleted_instances"
        log_info "Waiting for VMSS to provision replacement instances..."
        
        # Wait for replacement instances to be created and reach running state
        wait_for_vmss_replacement "$vmss_name" "$node_rg" "$nodepool" $failed_count
    else
        log_warning "No instances were successfully deleted"
    fi
    
    log_info "VM deletion and replacement operations completed for all failed instances"
}

# Wait for VMSS to provision replacement instances after deletion
function wait_for_vmss_replacement() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3
    local expected_replacements=$4
    local max_wait_time=1800  # 30 minutes
    local check_interval=60   # 1 minute
    local elapsed=0
    
    log_info "Waiting for $expected_replacements replacement VM instances to be provisioned..."
    
    while [ $elapsed -lt $max_wait_time ]; do
        # Check for cancellation
        if ! check_cancellation; then
            log_warning "Operation cancelled during VMSS replacement wait"
            return 1
        fi
        
        # Check current instance count and their states
        local instance_info
        instance_info=$(az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output json 2>/dev/null || echo "[]")
        
        local total_instances=$(echo "$instance_info" | jq length)
        local running_instances=$(echo "$instance_info" | jq '[.[] | select(.ProvisioningState=="Succeeded" and (.PowerState=="VM running" or .PowerState==null))] | length')
        local creating_instances=$(echo "$instance_info" | jq '[.[] | select(.ProvisioningState=="Creating")] | length')
        local failed_instances=$(echo "$instance_info" | jq '[.[] | select(.ProvisioningState=="Failed")] | length')
        
        log_info "VMSS instance status - Total: $total_instances, Running: $running_instances, Creating: $creating_instances, Failed: $failed_instances (elapsed: ${elapsed}s)"
        
        # Check if we have sufficient healthy instances
        if [ $running_instances -gt 0 ] && [ $failed_instances -eq 0 ] && [ $creating_instances -eq 0 ]; then
            log_info "All replacement instances are now running successfully"
            return 0
        elif [ $failed_instances -gt 0 ]; then
            log_warning "Detected $failed_instances new failed instances during replacement"
            # Don't return error here as we'll handle it in the outer loop
        fi
        
        # Show detailed status for troubleshooting if taking longer than expected
        if [ $elapsed -gt 600 ] && [ $((elapsed % 300)) -eq 0 ]; then
            log_info "Detailed instance status after $((elapsed / 60)) minutes:"
            echo "$instance_info" | jq -r '.[] | "\(.InstanceId): \(.ProvisioningState) - \(.PowerState // "Unknown")"' | head -10
        fi
        
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    log_warning "Timeout waiting for VMSS replacement instances after $((max_wait_time / 60)) minutes"
    log_info "Final VMSS instance status:"
    az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
        --output table 2>/dev/null || log_warning "Unable to retrieve final VMSS status"
    
    return 1
}

# Label a specific number of nodes with swiftv2slo=true across nodepools (batch operation)
function label_swiftv2slo_nodes() {
    local total_nodes_to_label=$1

    log_info "Labeling $total_nodes_to_label nodes with swiftv2slo=true..."

    # Get ready nodes from user nodepools using kubectl label selector
    local kubectl_output
    if ! kubectl_output=$(kubectl get nodes \
        -l 'agentpool,agentpool!=promnodepool,!swiftv2slo' \
        -o json 2>&1); then
        log_error "kubectl get nodes failed while selecting nodes to label: $kubectl_output"
        return 1
    fi

    local unlabeled_nodes
    unlabeled_nodes=$(echo "$kubectl_output" | jq -r '.items[] |
            select(.metadata.labels.agentpool | startswith("userpool")) |
            select(.status.conditions[] | select(.type=="Ready" and .status=="True")) |
            .metadata.name' | grep -v '^$' | head -n "$total_nodes_to_label")

    # Check if we have any nodes
    if [ -z "$unlabeled_nodes" ]; then
        log_warning "No unlabeled ready nodes found to label with swiftv2slo=true"
        return 1
    fi
    
    # Convert to array for proper counting and handling
    local -a node_array
    readarray -t node_array <<< "$unlabeled_nodes"
    
    # Filter out empty elements
    local -a filtered_nodes=()
    for node in "${node_array[@]}"; do
        if [ -n "$node" ]; then
            filtered_nodes+=("$node")
        fi
    done
    
    local node_count=${#filtered_nodes[@]}
    
    # Validate we have nodes to label
    if [ "$node_count" -eq 0 ]; then
        log_warning "No valid nodes to label"
        return 1
    fi
    
    log_info "Found $node_count node(s) to label (requested: $total_nodes_to_label)"
    
    # Actually label the nodes
    local labeled_count=0
    local failed_count=0
    
    for node in "${filtered_nodes[@]}"; do
        if kubectl label node "$node" swiftv2slo=true --overwrite 2>/dev/null; then
            labeled_count=$((labeled_count + 1))
            log_info "Successfully labeled node: $node ($labeled_count/$node_count)"
        else
            failed_count=$((failed_count + 1))
            log_warning "Failed to label node: $node"
        fi
    done
    
    log_info "Labeling complete: $labeled_count successful, $failed_count failed"
    
    if [ "$labeled_count" -eq 0 ]; then
        log_error "Failed to label any nodes"
        return 1
    fi
    
    if [ "$labeled_count" -lt "$total_nodes_to_label" ]; then
        log_warning "Only labeled $labeled_count/$total_nodes_to_label requested nodes"
    fi
    
    return 0
}

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
    
    # Poll for node readiness
    while [ $elapsed -lt $node_readiness_timeout ]; do
        # Check for cancellation
        if ! check_cancellation; then
            log_warning "Operation cancelled during node readiness verification"
            return 1
        fi
        
        # Query node status for this nodepool
        local READY_NODES
        READY_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | grep " Ready " | wc -l 2>/dev/null)
        READY_NODES=${READY_NODES:-0}
        
        local NOT_READY_NODES
        NOT_READY_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | grep " NotReady " | wc -l 2>/dev/null)
        NOT_READY_NODES=${NOT_READY_NODES:-0}
        
        local TOTAL_NODES
        TOTAL_NODES=$(kubectl get nodes -l agentpool="$nodepool" --no-headers 2>/dev/null | wc -l 2>/dev/null)
        TOTAL_NODES=${TOTAL_NODES:-0}
        
        log_info "Node readiness for '$nodepool': $READY_NODES ready, $NOT_READY_NODES not ready, $TOTAL_NODES total (target: $expected_nodes, elapsed: ${elapsed}s)"
        
        # Success condition: all expected nodes are ready
        if [ "$READY_NODES" -eq "$expected_nodes" ] && [ "$READY_NODES" -gt 0 ]; then
            log_info "All $READY_NODES nodes in nodepool '$nodepool' are ready"
            return 0
        fi
        
        # Handle different scenarios
        if [ "$TOTAL_NODES" -lt "$expected_nodes" ]; then
            log_info "Waiting for provisioning: $TOTAL_NODES/$expected_nodes nodes visible in Kubernetes"
        elif [ "$READY_NODES" -eq 0 ] && [ $elapsed -gt 300 ]; then
            log_info "No ready nodes after 5+ minutes, checking node conditions..."
            kubectl get nodes -l agentpool="$nodepool" \
                -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,REASON:.status.conditions[-1].reason \
                2>/dev/null || true
        else
            log_info "Node readiness progressing: $READY_NODES/$expected_nodes ready"
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
    
    # Timeout reached
    log_error "Timeout waiting for nodes in nodepool '$nodepool' to be ready"
    
    # Show final node status
    log_info "Final node status:"
    kubectl get nodes -l agentpool="$nodepool" -o wide 2>/dev/null || echo "Unable to get node status"
    
    # Check if we should fail hard when buffer nodes are not available
    if [ "${PROVISION_BUFFER_NODES:-true}" = "false" ]; then
        log_error "PROVISION_BUFFER_NODES is false and not all nodes are ready. Failing the script."
        exit 1
    fi
    
    return 1
}

# Get total ready nodes across all user and buffer nodepools
function get_total_ready_nodes() {
    local cluster_name=$1
    local resource_group=$2
    
    log_info "Checking total ready nodes across all user and buffer nodepools..." >&2
    
    # Get kubeconfig
    az aks get-credentials --name "$cluster_name" --resource-group "$resource_group" --admin --overwrite-existing >/dev/null 2>&1
    
    # Count ready nodes with user nodepool labels (including buffer pools)
    local ready_nodes
    ready_nodes=$(kubectl get nodes \
        -l agentpool \
        -o jsonpath='{range .items[*]}{.metadata.labels.agentpool}{" "}{range .status.conditions[*]}{.type}={.status}{" "}{end}{"\n"}{end}' 2>/dev/null | \
        grep -E "(userpool|bufferpool)" | \
        grep "Ready=True" | \
        wc -l || echo "0")
    
    log_info "Total ready nodes in user/buffer pools: $ready_nodes" >&2
    echo "$ready_nodes"
}

# Check if VM repair is needed based on ready node count
function is_vm_repair_needed() {
    local cluster_name=$1
    local resource_group=$2
    local target_nodes=$3
    
    local ready_nodes
    ready_nodes=$(get_total_ready_nodes "$cluster_name" "$resource_group")
    
    if [[ $ready_nodes -ge $target_nodes ]]; then
        log_info "Sufficient ready nodes ($ready_nodes >= $target_nodes). VM repair not needed."
        return 1  # Not needed
    else
        log_info "Insufficient ready nodes ($ready_nodes < $target_nodes). VM repair needed."
        return 0  # Needed
    fi
}

# Verify total healthy node count across all relevant nodepools
function verify_total_node_capacity() {
    local cluster_name=$1
    local resource_group=$2
    local required_nodes=$3
    
    log_info "Verifying total healthy node capacity meets requirement of $required_nodes nodes"
    
    # Get all nodepools including user and buffer pools
    local all_nodepools
    all_nodepools=$(az aks nodepool list \
        --cluster-name "$cluster_name" \
        --resource-group "$resource_group" \
        --query "[?mode=='User' && name!='promnodepool' && !contains(name, 'devtest')].{name:name, count:count, powerState:powerState.code}" \
        --output json)
    
    local total_healthy_nodes=0
    local nodepool_details=""
    
    # Calculate total healthy nodes from user and buffer pools
    while IFS= read -r nodepool; do
        local name=$(echo "$nodepool" | jq -r '.name')
        local count=$(echo "$nodepool" | jq -r '.count')
        local power_state=$(echo "$nodepool" | jq -r '.powerState')
        
        if [[ "$power_state" == "Running" ]]; then
            total_healthy_nodes=$((total_healthy_nodes + count))
            nodepool_details+="  $name: $count nodes (Running)\n"
        else
            log_warning "Nodepool '$name' is not in Running state (current: $power_state)"
            nodepool_details+="  $name: $count nodes ($power_state)\n"
        fi
    done < <(echo "$all_nodepools" | jq -c '.[]')
    
    log_info "Total healthy node count summary:"
    echo -e "$nodepool_details"
    log_info "Total healthy nodes: $total_healthy_nodes (required: $required_nodes)"
    
    if [[ $total_healthy_nodes -ge $required_nodes ]]; then
        log_info "✓ Total healthy node count ($total_healthy_nodes) meets requirement ($required_nodes)"
        return 0
    else
        log_warning "✗ Total healthy node count ($total_healthy_nodes) is below requirement ($required_nodes)"
        local deficit=$((required_nodes - total_healthy_nodes))
        log_warning "Node deficit: $deficit nodes"
        return 1
    fi
}

# Validate required environment variables
function validate_environment() {
    local missing_vars=""
    
    [ -z "${REGION:-}" ] && missing_vars="$missing_vars REGION"
    [ -z "${ROLE:-}" ] && missing_vars="$missing_vars ROLE"
    [ -z "${NODE_COUNT:-}" ] && missing_vars="$missing_vars NODE_COUNT"
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
    log_info "  Desired total user nodes (NODE_COUNT): $NODE_COUNT"
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

    local total_user_nodepools
    total_user_nodepools=$(echo "$usernodepools" | wc -w)
    log_info "Discovered $total_user_nodepools user nodepool(s): $usernodepools"

    # Treat NODE_COUNT as TOTAL desired user nodes across all userpool* pools.
    # Fill pools sequentially (userpool1, userpool2, ...) up to 500 nodes each.
    local total_target=${NODE_COUNT}
    if [[ -z "$total_target" || "$total_target" -le 0 ]]; then
        log_warning "Total desired user node count invalid ('$total_target'); defaulting to 1"
        total_target=1
    fi

    declare -A CURRENT_COUNTS
    declare -A TARGETS
    local current_total=0

    # Gather current counts first
    for nodepool in $usernodepools; do
        # Check for cancellation before gathering nodepool info
        if ! check_cancellation; then
            log_error "Pipeline cancelled while gathering nodepool information"
            exit 143
        fi
        
        local cnt
        cnt=$(get_nodepool_count "$aks_name" "$nodepool" "$aks_rg")
        CURRENT_COUNTS[$nodepool]=$cnt
        current_total=$((current_total + cnt))
    done

    log_info "Current total user nodes across pools: $current_total"

    if [[ $current_total -ge $total_target ]]; then
        log_warning "Current total ($current_total) already >= desired total ($total_target). No scale up performed (no scale down logic)."
        for nodepool in $usernodepools; do
            TARGETS[$nodepool]=${CURRENT_COUNTS[$nodepool]}
        done
        total_required_nodes=$current_total
    else
        local remaining=$((total_target - current_total))
        log_info "Need to add $remaining node(s) across pools to reach target $total_target"
        for nodepool in $usernodepools; do
            local current=${CURRENT_COUNTS[$nodepool]}
            local capacity=$((500 - current))
            if [[ $capacity -le 0 || $remaining -le 0 ]]; then
                TARGETS[$nodepool]=$current
                continue
            fi
            local add=$capacity
            if [[ $add -gt $remaining ]]; then
                add=$remaining
            fi
            TARGETS[$nodepool]=$((current + add))
            remaining=$((remaining - add))
        done
        if [[ $remaining -gt 0 ]]; then
            log_warning "Unable to reach desired total ($total_target). Remaining $remaining node(s) exceed aggregate capacity of existing pools (max 500 each)."
        fi
        # Compute total_required_nodes as sum of targets
        total_required_nodes=0
        for nodepool in $usernodepools; do
            total_required_nodes=$((total_required_nodes + TARGETS[$nodepool]))
        done
    fi

    log_info "Planned per-pool targets (sequential fill up to 500 each):"
    for nodepool in $usernodepools; do
        log_info "  $nodepool: current=${CURRENT_COUNTS[$nodepool]} -> target=${TARGETS[$nodepool]}"
    done
    log_info "Aggregate planned total: $total_required_nodes (desired: $total_target)"

    # Track scale failures
    local scale_failures=0
    declare -A SCALE_FAILED
    
    # Process each nodepool with its computed target
    for nodepool in $usernodepools; do
        # Check for cancellation before processing each nodepool
        if ! check_cancellation; then
            log_error "Pipeline cancelled before processing nodepool '$nodepool'"
            exit 143
        fi
        
        local pool_target=${TARGETS[$nodepool]}
        local current_nodes=${CURRENT_COUNTS[$nodepool]}
        log_info "=== Processing nodepool: '$nodepool' current=$current_nodes target=$pool_target ==="
        if [[ $pool_target -gt $current_nodes ]]; then
            log_info "Scaling nodepool '$nodepool': $current_nodes → $pool_target"
            if ! scale_nodepool "$aks_name" "$nodepool" "$aks_rg" "$pool_target"; then
                scale_failures=$((scale_failures + 1))
                SCALE_FAILED[$nodepool]=1
                log_warning "Scale incomplete for nodepool '$nodepool', VM repair will attempt to fix issues..."
            fi
            log_info "Waiting 60 seconds for scale operation to stabilize..."
            sleep 60
        else
            log_info "No scale up needed for $nodepool (current >= target)"
        fi
        log_info "Completed processing nodepool '$nodepool'"
    done
    
    if [ $scale_failures -gt 0 ]; then
        log_warning "Scale operations failed for $scale_failures nodepool(s)"
    fi
    
    log_info "Verifying overall cluster capacity..."
    log_info "Expected user nodepools: $total_user_nodepools"
    log_info "Expected total required nodes (sum of per-pool targets): $total_required_nodes"
    
    # Check if VM repair is needed based on total ready node count
    if is_vm_repair_needed "$aks_name" "$aks_rg" "$total_required_nodes"; then
        # Check for cancellation before starting VM repair
        if ! check_cancellation; then
            log_error "Pipeline cancelled before VM repair operations"
            exit 143
        fi
        
        log_info "Insufficient ready nodes detected. Performing failed VM cleanup and replacement..."
        
        # Process each nodepool for VM repair
        for nodepool in $usernodepools; do
            # Check for cancellation before each nodepool repair
            if ! check_cancellation; then
                log_warning "Pipeline cancelled during VM repair for nodepool '$nodepool'"
                exit 143
            fi
            
            log_info "=== Cleaning up failed VMs for nodepool: '$nodepool' ==="
            
            # List VM status and get VMSS info
            local vmss_info
            vmss_info=$(list_vm_status "$nodepool" "$aks_name" "$aks_rg")
            IFS=':' read -r vmss_name node_rg <<< "$vmss_info"
            
            # Delete any failed VMs to trigger replacement
            repair_failed_vms "$vmss_name" "$node_rg" "$nodepool"
            
            # Verify all nodes are ready in Kubernetes
            local pool_target=${TARGETS[$nodepool]:-${CURRENT_COUNTS[$nodepool]}}
            if ! verify_node_readiness "$nodepool" "$aks_name" "$aks_rg" "$pool_target"; then
                log_warning "Node readiness verification failed for nodepool '$nodepool', but continuing..."
            fi
            
            log_info "Completed failed VM cleanup for nodepool '$nodepool'"
        done
        
        # Final check after cleanup and replacement
        log_info "Verifying node count after VM cleanup and replacement..."
        local final_ready_nodes
        final_ready_nodes=$(get_total_ready_nodes "$aks_name" "$aks_rg")
        log_info "Final ready node count: $final_ready_nodes (required: $total_required_nodes)"
    else
        log_info "Sufficient ready nodes available. Skipping failed VM cleanup operations."
    fi
    
    # Label the required number of nodes with swiftv2slo=true
    log_info "Labeling $total_required_nodes nodes with swiftv2slo=true for workload placement..."
    if ! label_swiftv2slo_nodes "$total_required_nodes"; then
        log_warning "Node labeling encountered issues, but continuing..."
    fi
    
    # Final verification: if PROVISION_BUFFER_NODES is false, ensure we have exactly the required nodes
    if [ "${PROVISION_BUFFER_NODES:-true}" = "false" ]; then
        log_info "PROVISION_BUFFER_NODES is false. Performing strict final node count verification..."
        local final_ready_nodes
        final_ready_nodes=$(get_total_ready_nodes "$aks_name" "$aks_rg")
        
        if [ "$final_ready_nodes" -lt "$total_required_nodes" ]; then
            log_error "PROVISION_BUFFER_NODES is false and final ready node count ($final_ready_nodes) is less than required ($total_required_nodes)"
            log_error "Missing nodes: $((total_required_nodes - final_ready_nodes))"
            exit 1
        fi
        
        log_info "✓ Strict verification passed: $final_ready_nodes ready nodes >= $total_required_nodes required"
    else
        log_info "Final cluster state: $(get_total_ready_nodes "$aks_name" "$aks_rg") ready nodes available"
    fi
    
    log_info "All nodepool operations completed"
}

# Execute main function
main "$@"
