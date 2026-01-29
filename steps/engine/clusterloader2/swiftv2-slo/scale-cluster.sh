#!/bin/bash
set -euo pipefail

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

# Set up signal traps for cancellation (uses handle_cancellation from common.sh)
trap handle_cancellation SIGTERM SIGINT

# Track whether kubeconfig has been initialized for this run
KUBECONFIG_INITIALIZED=false

function ensure_kubeconfig() {
    local cluster_name=$1
    local resource_group=$2

    if [ "${KUBECONFIG_INITIALIZED}" = true ]; then
        return 0
    fi

    log_info "Initializing kubeconfig for cluster '$cluster_name'..." >&2
    if ! az aks get-credentials --name "$cluster_name" --resource-group "$resource_group" --admin --overwrite-existing >/dev/null 2>&1; then
        log_warning "Failed to get AKS credentials (kubectl operations may fail)" >&2
        return 1
    fi

    KUBECONFIG_INITIALIZED=true
    return 0
}

function kubectl_get_nodes_json() {
    local selector=${1:-}

    local output
    if [ -n "$selector" ]; then
        if ! output=$(kubectl get nodes -l "$selector" -o json 2>&1); then
            log_warning "kubectl get nodes failed (selector='$selector'): $output" >&2
            return 1
        fi
    else
        if ! output=$(kubectl get nodes -o json 2>&1); then
            log_warning "kubectl get nodes failed: $output" >&2
            return 1
        fi
    fi

    echo "$output"
    return 0
}

function count_ready_nodes_in_json() {
    local nodes_json=$1
    echo "$nodes_json" | jq '[.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))] | length' 2>/dev/null || echo "0"
}

function count_total_nodes_in_json() {
    local nodes_json=$1
    echo "$nodes_json" | jq '.items | length' 2>/dev/null || echo "0"
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
    local max_scale_retries=3
    local retry_delay=180  # Wait between retries (default 3 min)
    
    local scale_attempt=0
    local scale_success=false
    
    while [ $scale_attempt -lt $max_scale_retries ] && [ "$scale_success" = false ]; do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled during scale operation for nodepool '$nodepool'"
            return 1
        fi
        
        scale_attempt=$((scale_attempt + 1))
        
        if [ $scale_attempt -gt 1 ]; then
            log_info "Retrying scale operation for nodepool '$nodepool' (attempt $scale_attempt/$max_scale_retries)..."
            log_info "Waiting ${retry_delay}s before retry..."
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
        local vmss_stabilize_sleep=60
        log_info "Waiting ${vmss_stabilize_sleep}s for VMSS to stabilize..."
        sleep $vmss_stabilize_sleep
        
        # Verify actual VMSS instance count
        log_info "Verifying actual VMSS instance count for nodepool '$nodepool'..."
        local actual_count
        actual_count=$(get_vmss_instance_count "$nodepool" "$cluster_name" "$resource_group")
        
        log_info "VMSS actual count: $actual_count, target: $target_count (attempt $scale_attempt/$max_scale_retries)"
        
        if [ "$actual_count" -eq "$target_count" ]; then
            log_info "Successfully scaled nodepool '$nodepool' to $target_count nodes"
            scale_success=true
            return 0
        elif [ "$actual_count" -gt 0 ] && [ "$actual_count" -ge $((target_count - 5)) ]; then
            local shortfall=$((target_count - actual_count))
            if [ "${PROVISION_BUFFER_NODES}" = "true" ]; then
                log_info "Nodepool '$nodepool' has $actual_count/$target_count nodes ($shortfall VM(s) failed - buffer pool will provide additional capacity)"
            else
                log_info "Nodepool '$nodepool' has $actual_count/$target_count nodes ($shortfall VM(s) failed - VM repair will attempt to recover)"
            fi
            scale_success=true
            return 0
        else
            log_warning "Scale incomplete for nodepool '$nodepool': $actual_count/$target_count nodes provisioned (attempt $scale_attempt/$max_scale_retries)"
            
            # If this isn't the last retry, continue to next attempt
            if [ $scale_attempt -lt $max_scale_retries ]; then
                log_info "Will retry scaling operation..."
            fi
        fi
    done
    
    # All retries exhausted
    if [ "$scale_success" = false ]; then
        log_error "Failed to scale nodepool '$nodepool' to $target_count nodes after $max_scale_retries attempts. Later steps will attempt to recover"
        log_error "Final VMSS count: $(get_vmss_instance_count "$nodepool" "$cluster_name" "$resource_group")/$target_count"
        
    fi
    
    return 0
}

# Scale the buffer pool (userpoolBuffer) to handle shortfall when buffer pool exists
function scale_buffer_pool() {
    local cluster_name=$1
    local resource_group=$2
    local shortfall=$3
    
    local buffer_pool_name="userpoolBuffer"
    
    # Calculate target size (2x shortfall)
    local additional_nodes=$((shortfall * 2))
    log_info "=== Scaling buffer pool to handle shortfall ==="
    log_info "  Buffer pool: $buffer_pool_name"
    log_info "  Shortfall detected: $shortfall nodes"
    log_info "  Additional nodes to provision (2x shortfall): $additional_nodes nodes"
    
    # Get current buffer pool size
    log_info "Step 1/3: Getting current buffer pool size..."
    local current_count
    current_count=$(get_nodepool_count "$cluster_name" "$buffer_pool_name" "$resource_group" 2>/dev/null || echo "0")
    log_info "  Current buffer pool size: $current_count nodes"
    
    # Calculate new target
    local new_target=$((current_count + additional_nodes))
    
    # Cap at 500 nodes per pool
    if [ "$new_target" -gt 500 ]; then
        log_warning "Target $new_target exceeds max pool size, capping at 500"
        new_target=500
    fi
    
    log_info "  New target size: $new_target nodes"
    
    # Scale the buffer pool
    log_info "Step 2/3: Scaling buffer pool '$buffer_pool_name' from $current_count to $new_target nodes..."
    
    if ! scale_nodepool "$cluster_name" "$buffer_pool_name" "$resource_group" "$new_target"; then
        log_warning "Buffer pool scale operation did not fully succeed"
    fi
    
    # Wait for nodes to be ready
    log_info "Step 3/3: Waiting for buffer pool nodes to become ready..."
    sleep 30  # Initial stabilization
    
    if ! verify_node_readiness "$buffer_pool_name" "$new_target"; then
        log_warning "Not all nodes in buffer pool are ready, but continuing with available nodes"
    fi
    
    # Get final ready count
    local ready_count
    ready_count=$(kubectl get nodes -l agentpool="$buffer_pool_name" --no-headers 2>/dev/null | grep " Ready " | wc -l)
    log_info "=== Buffer pool scaling complete ==="
    log_info "  Pool name: $buffer_pool_name"
    log_info "  Previous size: $current_count nodes"
    log_info "  Target size: $new_target nodes"
    log_info "  Ready nodes: $ready_count"
    
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

        # Summarize VM instance states (avoid logging every instance for large pools)
        local instance_info
        instance_info=$(az vmss list-instances \
            --name "$vmss_name" \
            --resource-group "$node_rg" \
            --query "[].{InstanceId:instanceId,ProvisioningState:provisioningState,PowerState:instanceView.statuses[1].displayStatus}" \
            --output json 2>/dev/null || echo "[]")

        local total_instances
        total_instances=$(echo "$instance_info" | jq 'length' 2>/dev/null || echo "0")

        local succeeded_instances
        succeeded_instances=$(echo "$instance_info" | jq '[.[] | select(.ProvisioningState=="Succeeded")] | length' 2>/dev/null || echo "0")

        local non_succeeded_instances=$((total_instances - succeeded_instances))

        log_info "VMSS instance summary for '$nodepool' (vmss='$vmss_name'): total=$total_instances succeeded=$succeeded_instances non_succeeded=$non_succeeded_instances" >&2

        # Only report VMs that are NOT in Succeeded state, grouped by ProvisioningState.
        if [ "$non_succeeded_instances" -gt 0 ]; then
            local non_succeeded_states
            non_succeeded_states=$(echo "$instance_info" | jq -r '[.[] | select(.ProvisioningState != "Succeeded") | .ProvisioningState] | unique | .[]' 2>/dev/null || echo "")

            if [ -n "$non_succeeded_states" ]; then
                for state in $non_succeeded_states; do
                    local ids
                    ids=$(echo "$instance_info" | jq -r --arg st "$state" '[.[] | select(.ProvisioningState==$st) | .InstanceId] | join(",")' 2>/dev/null || echo "")
                    if [ -n "$ids" ]; then
                        log_warning "VMSS instances not Succeeded ($state): $ids" >&2
                    fi
                done
            fi
        fi
        
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
        if ! check_cancellation; then
            log_warning "Pipeline cancelled during VM repair"
            return 1
        fi
        
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

# Detect VMSS instances that are provisioned (Succeeded) but missing from Kubernetes
# and delete them so the VMSS can replace them.
function repair_unjoined_vms() {
    local vmss_name=$1
    local node_rg=$2
    local nodepool=$3

    local enabled=true
    local recheck_delay=180

    if [ "$enabled" != "true" ]; then
        log_info "Unjoined-VM repair disabled (REPAIR_UNJOINED_VMS=$enabled)" >&2
        return 0
    fi

    if [ -z "$vmss_name" ] || [ -z "$node_rg" ]; then
        return 0
    fi

    # Safety: ensure kubeconfig exists and kubectl works before doing any destructive action.
    if ! ensure_kubeconfig "$aks_name" "$aks_rg"; then
        log_warning "Skipping unjoined-VM repair because kubeconfig could not be initialized" >&2
        return 0
    fi

    local pool_nodes_json
    if ! pool_nodes_json=$(kubectl_get_nodes_json "agentpool=$nodepool"); then
        log_warning "Skipping unjoined-VM repair for '$nodepool' because kubectl failed" >&2
        return 0
    fi

    local pool_nodes_total
    pool_nodes_total=$(count_total_nodes_in_json "$pool_nodes_json")

    # If the pool has zero nodes in Kubernetes, it might be an auth/control-plane issue.
    # Don’t mass-delete VMSS instances based on an empty/failed Kubernetes view.
    if [ "$pool_nodes_total" -eq 0 ]; then
        log_warning "Kubernetes shows 0 nodes for agentpool '$nodepool'; skipping unjoined-VM deletion for safety" >&2
        return 0
    fi

    # Build a set of Kubernetes node names (lowercased) for this pool.
    local k8s_names_json
    k8s_names_json=$(echo "$pool_nodes_json" | jq '[.items[].metadata.name | ascii_downcase]' 2>/dev/null || echo '[]')

    # Fetch VMSS instances (instanceId + computerName + provisioningState).
    local instances_json
    instances_json=$(az vmss list-instances \
        --name "$vmss_name" \
        --resource-group "$node_rg" \
        --query "[].{InstanceId:instanceId,ComputerName:osProfile.computerName,ProvisioningState:provisioningState}" \
        --output json 2>/dev/null || echo "[]")

    # Identify instances that are Succeeded in Azure but missing from Kubernetes.
    local missing_ids
    missing_ids=$(echo "$instances_json" | jq -r --argjson k8s "$k8s_names_json" '
        [ .[]
          | select(.ProvisioningState=="Succeeded")
          | select(.ComputerName != null)
          | select((.ComputerName | ascii_downcase) as $n | ($k8s | index($n)) == null)
          | .InstanceId ] | unique | .[]
    ' 2>/dev/null || echo "")

    if [ -z "$missing_ids" ]; then
        return 0
    fi

    local missing_count
    missing_count=$(echo "$missing_ids" | wc -w | tr -d ' ')

    # Recheck after a short delay to avoid deleting instances that are still joining.
    log_warning "Detected $missing_count VMSS instance(s) provisioned but not registered in Kubernetes for '$nodepool'. Rechecking in ${recheck_delay}s..." >&2
    log_warning "Candidate instance IDs: $(echo "$missing_ids" | tr '\n' ' ')" >&2
    sleep "$recheck_delay"

    if ! pool_nodes_json=$(kubectl_get_nodes_json "agentpool=$nodepool"); then
        log_warning "Skipping unjoined-VM deletion after recheck (kubectl failed)" >&2
        return 0
    fi
    k8s_names_json=$(echo "$pool_nodes_json" | jq '[.items[].metadata.name | ascii_downcase]' 2>/dev/null || echo '[]')
    missing_ids=$(echo "$instances_json" | jq -r --argjson k8s "$k8s_names_json" '
        [ .[]
          | select(.ProvisioningState=="Succeeded")
          | select(.ComputerName != null)
          | select((.ComputerName | ascii_downcase) as $n | ($k8s | index($n)) == null)
          | .InstanceId ] | unique | .[]
    ' 2>/dev/null || echo "")

    if [ -z "$missing_ids" ]; then
        log_info "Unjoined-VM candidates appear to have joined after recheck; no deletions needed." >&2
        return 0
    fi

    missing_count=$(echo "$missing_ids" | wc -w | tr -d ' ')

    log_warning "Deleting $missing_count VMSS instance(s) that are missing from Kubernetes (nodepool='$nodepool', vmss='$vmss_name')..." >&2

    local max_retries=3
    local retry_delay=30
    local deleted_count=0
    local deleted_instances=""

    for instance_id in $missing_ids; do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled during unjoined VM repair"
            return 1
        fi
        
        local retry_count=0
        local delete_success=false

        while [ $retry_count -lt $max_retries ] && [ "$delete_success" = false ]; do
            retry_count=$((retry_count + 1))

            if [ $retry_count -gt 1 ]; then
                log_info "Retry attempt $retry_count/$max_retries for deleting unjoined VM instance '$instance_id'" >&2
                sleep $retry_delay
            fi

            if timeout 180 az vmss delete-instances \
                --name "$vmss_name" \
                --resource-group "$node_rg" \
                --instance-ids "$instance_id" \
                --no-wait 2>/dev/null; then
                delete_success=true
                deleted_count=$((deleted_count + 1))
                deleted_instances="$deleted_instances $instance_id"
                log_info "Successfully initiated deletion for unjoined instance '$instance_id'" >&2
            else
                local exit_code=$?
                if [ $retry_count -lt $max_retries ]; then
                    log_warning "Delete attempt $retry_count failed for unjoined instance '$instance_id' (exit code: $exit_code), will retry..." >&2
                else
                    log_warning "All $max_retries delete attempts failed for unjoined instance '$instance_id' (exit code: $exit_code)" >&2
                fi
            fi
        done
    done

    if [ $deleted_count -gt 0 ]; then
        log_info "Successfully initiated deletion for unjoined instances:$deleted_instances" >&2
        log_info "Waiting for VMSS to provision replacement instances for deleted unjoined VMs..." >&2
        wait_for_vmss_replacement "$vmss_name" "$node_rg" "$nodepool" $deleted_count || true
    fi

    return 0
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
        if ! check_cancellation; then
            log_warning "Pipeline cancelled while waiting for VMSS replacement"
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

    # First, count nodes that are already labeled with swiftv2slo=true
    local already_labeled_count=0
    local already_labeled_output
    if already_labeled_output=$(kubectl get nodes \
        -l 'agentpool,agentpool!=promnodepool,swiftv2slo=true' \
        -o json 2>&1); then
        already_labeled_count=$(echo "$already_labeled_output" | jq -r '[.items[] |
            select(.metadata.labels.agentpool | startswith("userpool")) |
            select(.status.conditions[] | select(.type=="Ready" and .status=="True"))] | length' 2>/dev/null || echo "0")
    fi
    
    log_info "Nodes already labeled with swiftv2slo=true: $already_labeled_count"
    
    # Calculate how many additional nodes need to be labeled
    local nodes_needed=$((total_nodes_to_label - already_labeled_count))
    
    if [ "$nodes_needed" -le 0 ]; then
        log_info "Already have $already_labeled_count labeled nodes (required: $total_nodes_to_label). No additional labeling needed."
        return 0
    fi
    
    log_info "Need to label $nodes_needed additional node(s) to reach target of $total_nodes_to_label"

    # Get ready nodes from user nodepools that are NOT already labeled
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
            .metadata.name' | grep -v '^$' | head -n "$nodes_needed")

    # Check if we have any nodes to label
    if [ -z "$unlabeled_nodes" ]; then
        log_warning "No unlabeled ready nodes found to label with swiftv2slo=true"
        if [ "$already_labeled_count" -ge "$total_nodes_to_label" ]; then
            return 0
        fi
        log_error "Insufficient nodes: have $already_labeled_count labeled, need $total_nodes_to_label"
        return 1
    fi
    
    # Convert to array for proper counting and handling
    local -a node_array
    readarray -t node_array <<< "$unlabeled_nodes"
    
    # Filter out empty elements
    local -a nodes_to_label=()
    for node in "${node_array[@]}"; do
        if [ -n "$node" ]; then
            nodes_to_label+=("$node")
        fi
    done
    
    local node_count=${#nodes_to_label[@]}
    
    # Validate we have nodes to label
    if [ "$node_count" -eq 0 ]; then
        log_warning "No valid nodes to label"
        if [ "$already_labeled_count" -ge "$total_nodes_to_label" ]; then
            return 0
        fi
        return 1
    fi
    
    log_info "Found $node_count unlabeled node(s) to label (need: $nodes_needed)"
    
    # Use common utility function with retry logic from aks-utils.sh
    if ! label_nodes_with_retry "swiftv2slo=true" "${nodes_to_label[@]}"; then
        log_error "Failed to label all nodes with swiftv2slo=true"
        return 1
    fi
    
    # Calculate total labeled nodes (already + newly labeled)
    local total_labeled=$((already_labeled_count + node_count))
    
    if [ "$total_labeled" -lt "$total_nodes_to_label" ]; then
        local missing=$((total_nodes_to_label - total_labeled))
        log_error "Only have $total_labeled/$total_nodes_to_label labeled nodes ($missing nodes missing)"
        return 1
    fi
    
    log_info "Successfully labeled $node_count new nodes with swiftv2slo=true (total labeled: $total_labeled)"
    return 0
}

# Verify that all nodes in a nodepool are ready in Kubernetes
function verify_node_readiness() {
    local nodepool=$1
    local expected_nodes=$2
    
    if [ "$expected_nodes" -le 0 ]; then
        log_warning "No nodes to verify in nodepool '$nodepool'"
        return 1
    fi
    
    log_info "Verifying node readiness for nodepool '$nodepool' (expecting $expected_nodes nodes)..."
    
    local node_readiness_timeout=900  # default 15 minutes
    local RETRY_INTERVAL=60  # default 60 seconds
    local elapsed=0
    
    # Poll for node readiness
    while [ $elapsed -lt $node_readiness_timeout ]; do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled while verifying node readiness for '$nodepool'"
            return 1
        fi
        
        local nodes_json
        if ! nodes_json=$(kubectl_get_nodes_json "agentpool=$nodepool"); then
            log_warning "kubectl unavailable while verifying readiness for '$nodepool'; retrying..." >&2
            sleep $RETRY_INTERVAL
            elapsed=$((elapsed + RETRY_INTERVAL))
            continue
        fi

        local READY_NODES
        READY_NODES=$(count_ready_nodes_in_json "$nodes_json")

        local TOTAL_NODES
        TOTAL_NODES=$(count_total_nodes_in_json "$nodes_json")

        local NOT_READY_NODES=$((TOTAL_NODES - READY_NODES))
        
        log_info "Node readiness for '$nodepool': $READY_NODES ready, $NOT_READY_NODES not ready, $TOTAL_NODES total (expected: $expected_nodes, elapsed: ${elapsed}s)"
        
        # Success condition: expected nodes are ready
        if [ "$READY_NODES" -ge "$expected_nodes" ]; then
            log_info "All $expected_nodes expected nodes in nodepool '$nodepool' are ready"
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
    log_error "Timeout waiting for $expected_nodes nodes in nodepool '$nodepool' to be ready"
    
    # Show final node status
    log_info "Final node status:"
    kubectl get nodes -l agentpool="$nodepool" -o wide 2>/dev/null || echo "Unable to get node status"
    
    return 1
}

# Get total ready nodes across all user and buffer nodepools
function get_total_ready_nodes() {
    local cluster_name=$1
    local resource_group=$2
    
    log_info "Checking total ready nodes across all user and buffer nodepools..." >&2
    
    ensure_kubeconfig "$cluster_name" "$resource_group" >/dev/null 2>&1 || true

    local nodes_json
    if ! nodes_json=$(kubectl_get_nodes_json "agentpool"); then
        echo "0"
        return 0
    fi

    # Count Ready=True nodes across user/buffer pools.
    local ready_nodes
    ready_nodes=$(echo "$nodes_json" | jq '[
        .items[]
        | select(.metadata.labels.agentpool != null)
        | select(.metadata.labels.agentpool | test("(userpool|bufferpool)"; "i"))
        | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))
    ] | length' 2>/dev/null || echo "0")
    
    log_info "Total ready nodes in user/buffer pools: $ready_nodes" >&2
    echo "$ready_nodes"
}

# Check if there's a node shortfall based on ready node count
function has_node_shortfall() {
    local cluster_name=$1
    local resource_group=$2
    local target_nodes=$3
    
    local ready_nodes
    ready_nodes=$(get_total_ready_nodes "$cluster_name" "$resource_group")
    
    if [[ $ready_nodes -ge $target_nodes ]]; then
        log_info "Sufficient ready nodes ($ready_nodes >= $target_nodes). No shortfall detected."
        return 1  # No shortfall
    else
        log_info "Insufficient ready nodes ($ready_nodes < $target_nodes). Shortfall detected."
        return 0  # Has shortfall
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

# =============================================================================
# MAIN WORKFLOW FUNCTIONS
# =============================================================================

# Calculate per-pool scaling targets using sequential fill strategy
# Sets global: CURRENT_COUNTS, TARGETS, total_required_nodes
function calculate_scaling_targets() {
    local usernodepools=$1
    local total_target=$2
    
    local current_total=0

    # Gather current counts first
    for nodepool in $usernodepools; do
        local cnt
        cnt=$(get_nodepool_count "$aks_name" "$nodepool" "$aks_rg")
        CURRENT_COUNTS[$nodepool]=$cnt
        current_total=$((current_total + cnt))
    done

    log_info "Current total user nodes across pools: $current_total"

    if [[ $current_total -ge $total_target ]]; then
        log_info "Current total ($current_total) already meets desired total ($total_target). No scaling needed."
        for nodepool in $usernodepools; do
            TARGETS[$nodepool]=${CURRENT_COUNTS[$nodepool]}
        done
        total_required_nodes=$current_total
    else
        local remaining=$((total_target - current_total))
        log_info "Need to add $remaining node(s) across pools to reach target $total_target"
        
        # Fill pools sequentially up to 500 nodes each
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

    # Log the plan
    log_info "Planned per-pool targets (sequential fill up to 500 each):"
    for nodepool in $usernodepools; do
        log_info "  $nodepool: current=${CURRENT_COUNTS[$nodepool]} -> target=${TARGETS[$nodepool]}"
    done
    log_info "Aggregate planned total: $total_required_nodes (desired: $total_target)"
}

# Scale all user nodepools to their targets
# Returns number of scale failures
function scale_user_nodepools() {
    local usernodepools=$1
    local scale_failures=0
    
    for nodepool in $usernodepools; do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled before processing nodepool '$nodepool'"
            return 1
        fi
        
        local pool_target=${TARGETS[$nodepool]}
        local current_nodes=${CURRENT_COUNTS[$nodepool]}
        
        log_info "=== Processing nodepool: '$nodepool' current=$current_nodes target=$pool_target ==="
        
        if [[ $pool_target -gt $current_nodes ]]; then
            log_info "Scaling nodepool '$nodepool': $current_nodes → $pool_target"
            
            if ! scale_nodepool "$aks_name" "$nodepool" "$aks_rg" "$pool_target"; then
                scale_failures=$((scale_failures + 1))
                SCALE_FAILED[$nodepool]=1
                
                if [ "${PROVISION_BUFFER_NODES}" = "true" ]; then
                    log_warning "Scale failed for nodepool '$nodepool'. Buffer pool should provide additional capacity."
                else
                    log_info "Scale did not reach target for nodepool '$nodepool'. VM repair phase will attempt to recover failed VMs."
                fi
            fi
            
            log_info "Waiting 60 seconds for scale operation to stabilize..."
            sleep 60
        else
            log_info "No scale up needed for $nodepool (current >= target)"
        fi
        
        log_info "Completed processing nodepool '$nodepool'"
    done
    
    if [ $scale_failures -gt 0 ]; then
        if [ "${PROVISION_BUFFER_NODES}" = "true" ]; then
            log_info "$scale_failures nodepool(s) did not reach full target. Buffer pool will provide additional capacity."
        else
            log_info "$scale_failures nodepool(s) did not reach full target. VM repair will attempt recovery."
        fi
    fi
    
    return $scale_failures
}

# Handle shortfall by scaling buffer pool
function handle_shortfall_with_buffer_pool() {
    local shortfall=$1
    
    log_info "=== Buffer pool mode: Scaling userpoolBuffer to handle shortfall ==="
    log_info "Strategy: Scale userpoolBuffer with 2x shortfall ($((shortfall * 2))) additional nodes"
    
    scale_buffer_pool "$aks_name" "$aks_rg" "$shortfall"
    local scale_result=$?
    
    if [ $scale_result -eq 0 ]; then
        log_info "✓ Buffer pool scaling completed"
        
        # Wait for 30 secs for stabilization before verification
        sleep 30
        log_info "Verifying node count after buffer pool scaling..."
        local post_scale_ready
        post_scale_ready=$(get_total_ready_nodes "$aks_name" "$aks_rg")
        log_info "Ready nodes after buffer pool scaling: $post_scale_ready (required: $total_required_nodes)"
        
        if [ "$post_scale_ready" -ge "$total_required_nodes" ]; then
            log_info "✓ Buffer pool scaling successfully provided enough nodes to meet requirement"
            return 0
        else
            log_error "Buffer pool scaled but total ready nodes ($post_scale_ready) still below requirement ($total_required_nodes)"
            log_error "Missing nodes: $((total_required_nodes - post_scale_ready))"
            return 1
        fi
    else
        log_error "Buffer pool scaling encountered issues"
        return 1
    fi
}

# Handle shortfall by repairing failed VMs
function handle_shortfall_with_vm_repair() {
    local usernodepools=$1
    
    log_info "=== No buffer pool mode: Performing VM repair ==="
    log_info "Strategy: Delete failed VMs to trigger VMSS replacement"
    
    ensure_kubeconfig "$aks_name" "$aks_rg" >/dev/null 2>&1 || true

    # Step 1: Repair failed VMs in all nodepools
    for nodepool in $usernodepools; do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled before VM repair for nodepool '$nodepool'"
            return 1
        fi
        
        log_info "--- VM repair for nodepool: '$nodepool' ---"
        
        log_info "Checking VM status for nodepool '$nodepool'..."
        local vmss_info
        vmss_info=$(list_vm_status "$nodepool" "$aks_name" "$aks_rg")
        IFS=':' read -r vmss_name node_rg <<< "$vmss_info"
        
        if [ -z "$vmss_name" ]; then
            log_warning "No VMSS found for nodepool '$nodepool', skipping"
            continue
        fi
        log_info "  VMSS: $vmss_name"
        log_info "  Node RG: $node_rg"
        
        log_info "Deleting failed VMs for nodepool '$nodepool'..."
        repair_failed_vms "$vmss_name" "$node_rg" "$nodepool"

        # Also repair instances that are provisioned but never joined Kubernetes (e.g., kubelet disabled).
        repair_unjoined_vms "$vmss_name" "$node_rg" "$nodepool"
        
        log_info "--- Completed VM repair for nodepool '$nodepool' ---"
    done
    
    # Step 2: Wait for total required nodes with retries
    log_info "Waiting for cluster to reach $total_required_nodes ready nodes..."
    
    local max_retries=3
    local retry_timeout=900  # 15 minutes per retry
    local retry_interval=120
    
    for attempt in $(seq 1 $max_retries); do
        if ! check_cancellation; then
            log_warning "Pipeline cancelled during node verification"
            return 1
        fi
        
        log_info "Verification attempt $attempt/$max_retries (timeout: $((retry_timeout / 60)) minutes)..."
        
        local elapsed=0
        while [ $elapsed -lt $retry_timeout ]; do
            if ! check_cancellation; then
                log_warning "Pipeline cancelled while waiting for nodes"
                return 1
            fi
            local ready_nodes
            ready_nodes=$(get_total_ready_nodes "$aks_name" "$aks_rg")
            
            log_info "Ready nodes: $ready_nodes / $total_required_nodes (elapsed: ${elapsed}s)"
            
            if [ "$ready_nodes" -ge "$total_required_nodes" ]; then
                log_info "✓ VM repair successfully recovered enough nodes to meet requirement"
                return 0
            fi
            
            sleep $retry_interval
            elapsed=$((elapsed + retry_interval))
        done
        
        if [ $attempt -lt $max_retries ]; then
            log_warning "Attempt $attempt timed out. Retrying..."
        fi
    done
    
    # All retries exhausted
    local final_ready_nodes
    final_ready_nodes=$(get_total_ready_nodes "$aks_name" "$aks_rg")
    log_error "VM repair failed after $max_retries attempts. Ready nodes: $final_ready_nodes (required: $total_required_nodes)"
    log_error "Missing nodes: $((total_required_nodes - final_ready_nodes))"
    return 1
}

# Recover from node shortfall using appropriate strategy
function recover_from_shortfall() {
    local usernodepools=$1
    local total_user_nodepools=$2
    
    log_info "Verifying overall cluster capacity..."
    log_info "Expected user nodepools: $total_user_nodepools"
    log_info "Expected total required nodes: $total_required_nodes"
    
    if has_node_shortfall "$aks_name" "$aks_rg" "$total_required_nodes"; then
        log_warning "Insufficient ready nodes detected."
        
        # Calculate shortfall
        local current_ready_nodes
        current_ready_nodes=$(get_total_ready_nodes "$aks_name" "$aks_rg")
        local shortfall=$((total_required_nodes - current_ready_nodes))
        
        log_info "Current ready nodes: $current_ready_nodes"
        log_info "Required nodes: $total_required_nodes"
        log_info "Shortfall: $shortfall nodes"
        
        if [ "${PROVISION_BUFFER_NODES}" = "true" ]; then
            if ! handle_shortfall_with_buffer_pool "$shortfall"; then
                log_error "Failed to recover from shortfall using buffer pool"
                return 1
            fi
        else
            if ! handle_shortfall_with_vm_repair "$usernodepools"; then
                log_error "Failed to recover from shortfall using VM repair"
                return 1
            fi
        fi
    else
        log_info "✓ Sufficient ready nodes available. No recovery operations needed."
    fi
    
    return 0
}

# Label nodes for workload placement
function label_nodes_for_workload() {
    log_info "Labeling $total_required_nodes nodes with swiftv2slo=true for workload placement..."
    
    if ! label_swiftv2slo_nodes "$total_required_nodes"; then
        log_error "Failed to label all required nodes ($total_required_nodes). Cluster does not have sufficient capacity."
        return 1
    fi
    
    return 0
}

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

function main() {
    validate_environment
    
    log_info "Starting AKS nodepool scaling operation"
    log_info "  Region: $REGION"
    log_info "  Role: $ROLE"
    log_info "  Desired total user nodes: $NODE_COUNT"
    log_info "  Run ID: $RUN_ID"
    log_info "  Buffer pool enabled: ${PROVISION_BUFFER_NODES:-false}"
    
    # Step 1: Discover cluster and nodepools
    find_aks_cluster "$REGION" "$ROLE"
    
    local usernodepools
    usernodepools=$(get_user_nodepools "$aks_name" "$aks_rg")
    if [ $? -ne 0 ]; then
        log_info "No user nodepools found to scale, exiting"
        exit 0
    fi

    local total_user_nodepools
    total_user_nodepools=$(echo "$usernodepools" | wc -w)
    log_info "Discovered $total_user_nodepools user nodepool(s): $usernodepools"

    # Validate target node count
    local total_target=${NODE_COUNT}
    if [[ -z "$total_target" || "$total_target" -le 0 ]]; then
        log_warning "Total desired user node count invalid ('$total_target'); defaulting to 1"
        total_target=1
    fi

    # Step 2: Calculate scaling targets
    declare -g -A CURRENT_COUNTS
    declare -g -A TARGETS
    declare -g -A SCALE_FAILED
    declare -g total_required_nodes=0
    
    calculate_scaling_targets "$usernodepools" "$total_target"
    
    # Step 3: Scale user nodepools
    scale_user_nodepools "$usernodepools"
    
    # Step 4: Recover from any shortfall
    if ! recover_from_shortfall "$usernodepools" "$total_user_nodepools"; then
        log_error "Failed to recover from node shortfall"
        exit 1
    fi
    
    # Step 5: Label nodes for workload placement
    if ! label_nodes_for_workload; then
        log_error "Failed to label nodes for workload"
        exit 1
    fi
    
    log_info "All nodepool operations completed successfully"
}

# Execute main function
main "$@"
