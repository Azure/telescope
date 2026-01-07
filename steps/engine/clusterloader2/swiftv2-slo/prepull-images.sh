#!/bin/bash
set -euo pipefail

# Pre-pull Container Images on Labeled Nodes
# This script creates DaemonSets to pull container images on all nodes labeled with swiftv2slo=true
# to reduce pod startup time during tests.
#
# Required Environment Variables:
# - DATAPATH_REPORTER_IMAGE (optional): Reporter image to pre-pull
# - NGINX_IMAGE (optional): Nginx image to pre-pull
# - IMAGE_PREPULL_BATCH_SIZE (optional): Number of nodes to pre-pull on simultaneously (default: 100)

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

DAEMONSET_TEMPLATE="$SCRIPT_DIR/prepull-daemonset-template.yaml"

# Pre-pull container images on all labeled nodes to reduce startup time
# Uses wave-based batching to avoid overwhelming container registry
function prepull_images_on_nodes() {
    local images_to_pull=("$@")
    local batch_size=${IMAGE_PREPULL_BATCH_SIZE:-100}  # Default to 100 nodes per batch
    
    if [ ${#images_to_pull[@]} -eq 0 ]; then
        log_info "No images specified for pre-pulling"
        return 0
    fi
    
    if [ ! -f "$DAEMONSET_TEMPLATE" ]; then
        log_error "DaemonSet template not found: $DAEMONSET_TEMPLATE"
        return 1
    fi
    
    log_info "Pre-pulling ${#images_to_pull[@]} container image(s) on nodes with swiftv2slo=true..."
    for img in "${images_to_pull[@]}"; do
        log_info "  - $img"
    done
    log_info "Using batched pre-pull strategy with batch size: $batch_size nodes"
    
    # Get list of all target nodes
    log_info "Discovering nodes with label swiftv2slo=true..."
    local all_nodes
    all_nodes=$(kubectl get nodes -l swiftv2slo=true -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$all_nodes" ]; then
        log_warning "No nodes found with label swiftv2slo=true, skipping image pre-pull"
        return 0
    fi
    
    # Convert to array
    local node_array=($all_nodes)
    local total_nodes=${#node_array[@]}
    log_info "Found $total_nodes nodes to pre-pull images on"
    
    # Calculate number of batches
    local num_batches=$(( (total_nodes + batch_size - 1) / batch_size ))  # Ceiling division
    log_info "Will process in $num_batches batch(es) of up to $batch_size nodes each"
    
    # Create a temporary namespace for pre-pull operations
    local prepull_ns="image-prepull-$$"
    log_info "Creating namespace '$prepull_ns' for pre-pull operations..."
    kubectl create namespace "$prepull_ns" 2>/dev/null || true
    
    # Process each batch
    local total_success=0
    local total_failed=0
    
    for ((batch_idx=0; batch_idx<num_batches; batch_idx++)); do
        local batch_num=$((batch_idx + 1))
        local start_idx=$((batch_idx * batch_size))
        local end_idx=$((start_idx + batch_size))
        if [ $end_idx -gt $total_nodes ]; then
            end_idx=$total_nodes
        fi
        
        local batch_nodes=("${node_array[@]:$start_idx:$((end_idx - start_idx))}")
        local batch_node_count=${#batch_nodes[@]}
        
        log_info "========================================"
        log_info "Processing batch $batch_num/$num_batches ($batch_node_count nodes)"
        log_info "========================================"
        
        # Label nodes in this batch with temporary batch label
        local batch_label="image-prepull-batch-$batch_idx"
        log_info "Labeling $batch_node_count nodes with $batch_label=true..."
        for node in "${batch_nodes[@]}"; do
            kubectl label node "$node" "$batch_label=true" --overwrite >/dev/null 2>&1 || true
        done
        
        # Create DaemonSet for each image targeting this batch
        local batch_ds_names=()
        for img in "${images_to_pull[@]}"; do
            # Sanitize image name for k8s resource naming
            local ds_name="prepull-b${batch_idx}-$(echo "$img" | sed 's|[^a-zA-Z0-9-]|-|g' | cut -c1-40)"
            local img_hash=$(echo "$img" | md5sum | cut -c1-8)
            batch_ds_names+=("$ds_name")
            
            log_info "Creating DaemonSet '$ds_name' for batch $batch_num..."
            
            # Generate DaemonSet from template with batch-specific node selector
            # Add batch label to node selector
            sed -e "s|IMAGE_PREPULL_NAMESPACE|$prepull_ns|g" \
                -e "s|IMAGE_PREPULL_NAME|$ds_name|g" \
                -e "s|IMAGE_HASH|$img_hash|g" \
                -e "s|IMAGE_TO_PULL|$img|g" \
                "$DAEMONSET_TEMPLATE" | \
                sed "/swiftv2slo: \"true\"/a\        $batch_label: \"true\"" | \
                kubectl apply -f - >/dev/null 2>&1
            
            if [ $? -eq 0 ]; then
                log_info "  ✓ DaemonSet '$ds_name' created"
            else
                log_warning "  ✗ Failed to create DaemonSet '$ds_name'"
            fi
        done
        
        # Wait for this batch to complete
        log_info "Waiting for batch $batch_num DaemonSets to complete..."
        local batch_max_wait=900  # 15 minutes per batch
        local batch_elapsed=0
        local batch_check_interval=10
        local batch_completed=false
        
        while [ $batch_elapsed -lt $batch_max_wait ]; do
            local batch_all_ready=true
            local batch_total_desired=0
            local batch_total_ready=0
            
            for ds_name in "${batch_ds_names[@]}"; do
                local ds_info
                ds_info=$(kubectl get daemonset "$ds_name" -n "$prepull_ns" -o json 2>/dev/null || echo "{}")
                
                local desired=$(echo "$ds_info" | jq -r '.status.desiredNumberScheduled // 0')
                local ready=$(echo "$ds_info" | jq -r '.status.numberReady // 0')
                
                batch_total_desired=$((batch_total_desired + desired))
                batch_total_ready=$((batch_total_ready + ready))
                
                if [ "$ready" -ne "$desired" ]; then
                    batch_all_ready=false
                fi
            done
            
            if [ "$batch_all_ready" = true ] && [ $batch_total_desired -gt 0 ]; then
                log_info "✓ Batch $batch_num completed successfully ($batch_total_ready/$batch_total_desired pods ready)"
                total_success=$((total_success + batch_node_count))
                batch_completed=true
                break
            fi
            
            if [ $((batch_elapsed % 30)) -eq 0 ]; then
                log_info "Batch $batch_num progress: $batch_total_ready/$batch_total_desired pods ready (elapsed: ${batch_elapsed}s)"
            fi
            
            sleep $batch_check_interval
            batch_elapsed=$((batch_elapsed + batch_check_interval))
        done
        
        if [ "$batch_completed" = false ]; then
            log_warning "Batch $batch_num timed out after $((batch_max_wait / 60)) minutes"
            total_failed=$((total_failed + batch_node_count))
        fi
        
        # Clean up batch-specific resources
        log_info "Cleaning up batch $batch_num resources..."
        for ds_name in "${batch_ds_names[@]}"; do
            kubectl delete daemonset "$ds_name" -n "$prepull_ns" --wait=false >/dev/null 2>&1 || true
        done
        
        # Remove batch labels from nodes
        for node in "${batch_nodes[@]}"; do
            kubectl label node "$node" "$batch_label-" >/dev/null 2>&1 || true
        done
        
        # Small delay between batches to allow registry to recover
        if [ $batch_num -lt $num_batches ]; then
            log_info "Waiting 10 seconds before next batch to allow registry recovery..."
            sleep 10
        fi
    done
    
    # Final cleanup: Delete the namespace
    log_info "Cleaning up namespace '$prepull_ns'..."
    kubectl delete namespace "$prepull_ns" --wait=false >/dev/null 2>&1 || true
    
    # Summary
    log_info "========================================"
    log_info "Image pre-pull operation completed"
    log_info "Total nodes: $total_nodes"
    log_info "Successful: $total_success"
    log_info "Failed/Timeout: $total_failed"
    log_info "========================================"
    
    return 0
}

# Main execution
function main() {
    log_info "Starting image pre-pull operation"
    
    # Collect images to pre-pull from environment variables
    local images_to_prepull=()
    
    if [ -n "${DATAPATH_REPORTER_IMAGE:-}" ]; then
        images_to_prepull+=("$DATAPATH_REPORTER_IMAGE")
        log_info "  DATAPATH_REPORTER_IMAGE: $DATAPATH_REPORTER_IMAGE"
    fi
    
    if [ -n "${NGINX_IMAGE:-}" ]; then
        images_to_prepull+=("$NGINX_IMAGE")
        log_info "  NGINX_IMAGE: $NGINX_IMAGE"
    fi
    
    if [ ${#images_to_prepull[@]} -eq 0 ]; then
        log_info "No image variables set, skipping image pre-pull"
        exit 0
    fi
    
    # Execute pre-pull
    if ! prepull_images_on_nodes "${images_to_prepull[@]}"; then
        log_warning "Image pre-pull had issues, but exiting successfully to allow test execution to continue"
        exit 0  # Don't fail the pipeline
    fi
    
    log_info "Image pre-pull completed successfully"
}

# Execute main function
main "$@"
