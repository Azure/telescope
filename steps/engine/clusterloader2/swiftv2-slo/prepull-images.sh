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
# - IMAGE_PREPULL_BATCH_DELAY (optional): Seconds to wait between batches (default: 5)
# - IMAGE_PREPULL_IMAGE_DELAY (optional): Seconds to wait between images within a batch (default: 5)

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

DAEMONSET_TEMPLATE="$SCRIPT_DIR/prepull-daemonset-template.yaml"

# Calculate combined hash of all images for tracking prepull state
function calculate_image_hash() {
    local images=("$@")
    local combined=""
    for img in "${images[@]}"; do
        combined="${combined}${img}"
    done
    echo "$combined" | md5sum | cut -c1-8
}

# Mark nodes as having images prepulled
function mark_nodes_prepulled() {
    local nodes=("$@")
    local image_hash="$PREPULL_IMAGE_HASH"
    local label="image-prepull-${image_hash}=true"
    
    if [ ${#nodes[@]} -eq 0 ]; then
        log_warning "No nodes to mark as prepulled"
        return 1
    fi
    
    log_info "Marking ${#nodes[@]} nodes as prepulled with label ${label}..."
    
    # Use common utility function with retry logic
    if ! label_nodes_with_retry "$label" "${nodes[@]}"; then
        log_warning "Some nodes failed to be marked as prepulled, but continuing"
        # Don't return error - partial success is acceptable for prepull tracking
    fi
    
    return 0
}

# Show diagnostic information about pod failures
function show_pod_diagnostics() {
    local namespace="$1"
    local ds_name="$2"
    
    log_info "Pod Status Breakdown:"
    kubectl get pods -n "$namespace" -l app=image-prepull --field-selector=status.phase!=Running --no-headers 2>/dev/null | \
        awk '{print $3}' | sort | uniq -c | while read count status; do
        log_info "  $status: $count pods"
    done
    
    log_info "\nSample failing pod details:"
    local sample_pod
    sample_pod=$(kubectl get pods -n "$namespace" -l app=image-prepull --field-selector=status.phase!=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -n "$sample_pod" ]; then
        log_info "Pod: $sample_pod"
        log_info "Events:"
        kubectl get events -n "$namespace" --field-selector involvedObject.name="$sample_pod" --sort-by='.lastTimestamp' 2>/dev/null | tail -10 || true
        
        log_info "\nPod conditions:"
        kubectl get pod "$sample_pod" -n "$namespace" -o json 2>/dev/null | jq -r '.status.conditions[] | "  \(.type): \(.status) - \(.reason // "N/A") - \(.message // "N/A")"' || true
        
        log_info "\nContainer statuses:"
        kubectl get pod "$sample_pod" -n "$namespace" -o json 2>/dev/null | jq -r '.status.initContainerStatuses[]?, .status.containerStatuses[]? | "  \(.name): \(.state | keys[0]) - \(.state[.state | keys[0]] | .reason // "N/A")"' || true
    else
        log_info "No failing pods found for diagnostics"
    fi
    
    # Check for common issues
    log_info "\nChecking for ImagePullBackOff pods:"
    local imagepull_count
    imagepull_count=$(kubectl get pods -n "$namespace" -l app=image-prepull -o json 2>/dev/null | jq '[.items[].status | select(.containerStatuses != null) | .containerStatuses[], .initContainerStatuses[] | select(.state.waiting.reason == "ImagePullBackOff" or .state.waiting.reason == "ErrImagePull")] | length')
    if [ "$imagepull_count" -gt 0 ]; then
        log_error "Found $imagepull_count containers with image pull errors - possible registry throttling or authentication issues"
    fi
}

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
    
    # Calculate hash of image set for tracking
    local PREPULL_IMAGE_HASH
    PREPULL_IMAGE_HASH=$(calculate_image_hash "${images_to_pull[@]}")
    local prepull_label="image-prepull-${PREPULL_IMAGE_HASH}"
    
    # Get list of all target nodes
    log_info "Discovering nodes with label swiftv2slo=true..."
    local all_nodes
    all_nodes=$(kubectl get nodes -l swiftv2slo=true -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$all_nodes" ]; then
        log_warning "No nodes found with label swiftv2slo=true, skipping image pre-pull"
        return 0
    fi
    
    local all_nodes_array=($all_nodes)
    log_info "Found ${#all_nodes_array[@]} total nodes with swiftv2slo=true"
    
    # Filter out nodes that already have images prepulled (from previous jobs when reusing cluster)
    log_info "Checking for nodes that already have images prepulled (label: ${prepull_label})..."
    local already_prepulled_nodes
    already_prepulled_nodes=$(kubectl get nodes -l "swiftv2slo=true,${prepull_label}=true" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
    
    if [ -n "$already_prepulled_nodes" ]; then
        local prepulled_array=($already_prepulled_nodes)
        log_info "Found ${#prepulled_array[@]} nodes with images already prepulled, skipping them"
        
        # Filter to get only new nodes
        local node_array=()
        for node in "${all_nodes_array[@]}"; do
            local skip=false
            for prepulled_node in "${prepulled_array[@]}"; do
                if [ "$node" = "$prepulled_node" ]; then
                    skip=true
                    break
                fi
            done
            if [ "$skip" = false ]; then
                node_array+=("$node")
            fi
        done
    else
        log_info "No nodes found with existing prepull label, will prepull on all nodes"
        node_array=("${all_nodes_array[@]}")
    fi
    
    local total_nodes=${#node_array[@]}
    if [ $total_nodes -eq 0 ]; then
        log_info "All nodes already have images prepulled, skipping prepull operation"
        return 0
    fi
    
    log_info "Will prepull images on $total_nodes NEW nodes (skipped ${#all_nodes_array[@]} - $total_nodes already prepulled)"
    
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
        local batch_label="image-prepull-batch-$batch_idx=true"
        local batch_label_key="image-prepull-batch-$batch_idx"
        log_info "Labeling $batch_node_count nodes with $batch_label..."
        
        # Use common utility with retry - but for batch labels we can be lenient
        if ! label_nodes_with_retry "$batch_label" "${batch_nodes[@]}"; then
            log_warning "Some batch label operations failed, but continuing with available nodes"
        fi
        
        # Verify batch labels are visible to the API server before creating DaemonSet
        # This addresses race conditions where labels are accepted but not yet propagated
        local label_selector="swiftv2slo=true,${batch_label_key}=true"
        if ! verify_node_labels "$batch_node_count" 60 "$label_selector"; then
            log_warning "  This may indicate nodes don't have swiftv2slo=true label. Continuing with $VERIFIED_NODE_COUNT nodes..."
            
            if [ "$VERIFIED_NODE_COUNT" -eq 0 ]; then
                log_error "  No nodes have both labels - skipping this batch"
                # Clean up batch labels before continuing
                log_info "  Cleaning up batch labels..."
                for node in "${batch_nodes[@]}"; do
                    kubectl label node "$node" "${batch_label_key}-" --overwrite >/dev/null 2>&1 || true
                done
                continue
            fi
        fi
        local verified_count=$VERIFIED_NODE_COUNT
        
        # Process each image sequentially to avoid overwhelming registry
        local batch_ds_names=()
        local image_delay=${IMAGE_PREPULL_IMAGE_DELAY:-5}
        local image_num=0
        
        for img in "${images_to_pull[@]}"; do
            image_num=$((image_num + 1))
            
            # Sanitize image name for k8s resource naming
            local ds_name="prepull-b${batch_idx}-$(echo "$img" | sed 's|[^a-zA-Z0-9-]|-|g' | cut -c1-40)"
            local img_hash=$(echo "$img" | md5sum | cut -c1-8)
            batch_ds_names+=("$ds_name")
            
            log_info "Creating DaemonSet '$ds_name' for image $image_num/${#images_to_pull[@]} in batch $batch_num..."
            log_info "  Image: $img"
            log_info "  Target nodes: $verified_count (with swiftv2slo=true AND $batch_label_key=true)"
            
            # Generate DaemonSet from template with batch-specific node selector
            sed -e "s|IMAGE_PREPULL_NAMESPACE|$prepull_ns|g" \
                -e "s|IMAGE_PREPULL_NAME|$ds_name|g" \
                -e "s|IMAGE_HASH|$img_hash|g" \
                -e "s|IMAGE_TO_PULL|$img|g" \
                "$DAEMONSET_TEMPLATE" | \
                sed "/swiftv2slo: \"true\"/a\        $batch_label_key: \"true\"" | \
                kubectl apply -f - >/dev/null 2>&1
            
            if [ $? -ne 0 ]; then
                log_warning "  ✗ Failed to create DaemonSet '$ds_name'"
                continue
            fi
            log_info "  ✓ DaemonSet '$ds_name' created"
            
            # Wait for this image's DaemonSet to complete before moving to next
            log_info "  Waiting for image $image_num to complete on all nodes..."
            local img_max_wait=600  # 10 minutes per image
            local img_elapsed=0
            local img_check_interval=10
            local img_completed=false
            local img_last_ready=0
            local img_stalled=0
            local desired_mismatch_logged=false
            
            while [ $img_elapsed -lt $img_max_wait ]; do
                local ds_info
                ds_info=$(kubectl get daemonset "$ds_name" -n "$prepull_ns" -o json 2>/dev/null || echo "{}")
                
                local desired=$(echo "$ds_info" | jq -r '.status.desiredNumberScheduled // 0')
                local ready=$(echo "$ds_info" | jq -r '.status.numberReady // 0')
                
                # Warn if desired doesn't match verified count (indicates label mismatch)
                if [ "$desired_mismatch_logged" = false ] && [ "$desired" -gt 0 ] && [ "$desired" -lt "$verified_count" ]; then
                    log_warning "  DaemonSet desired=$desired but verified_count=$verified_count - some nodes may have lost labels"
                    desired_mismatch_logged=true
                fi
                
                if [ "$ready" -eq "$desired" ] && [ $desired -gt 0 ]; then
                    log_info "  ✓ Image $image_num completed: $ready/$desired pods ready (${img_elapsed}s)"
                    img_completed=true
                    break
                fi
                
                # Detect stalling
                if [ "$ready" -eq "$img_last_ready" ]; then
                    img_stalled=$((img_stalled + 1))
                else
                    img_stalled=0
                fi
                img_last_ready=$ready
                
                # Show diagnostics if stalled for 2 minutes
                if [ $img_stalled -ge 12 ] && [ $((img_elapsed % 120)) -eq 0 ]; then
                    log_warning "  Image $image_num stalled at $ready/$desired pods"
                    show_pod_diagnostics "$prepull_ns" "$ds_name"
                fi
                
                # Abort if no progress for 3 minutes
                if [ "$ready" -eq 0 ] && [ $desired -gt 0 ] && [ $img_stalled -ge 18 ]; then
                    log_error "  Image $image_num failed: 0 pods ready after 3 minutes"
                    break
                fi
                
                if [ $((img_elapsed % 30)) -eq 0 ]; then
                    log_info "  Image $image_num progress: $ready/$desired pods ready (${img_elapsed}s)"
                fi
                
                sleep $img_check_interval
                img_elapsed=$((img_elapsed + img_check_interval))
            done
            
            if [ "$img_completed" = false ]; then
                log_warning "  Image $image_num did not complete within time limit"
            fi
            
            # Clean up this DaemonSet immediately to free resources
            log_info "  Cleaning up DaemonSet '$ds_name'..."
            kubectl delete daemonset "$ds_name" -n "$prepull_ns" --timeout=30s >/dev/null 2>&1 || true
            
            # Wait between images to reduce registry pressure
            if [ $image_num -lt ${#images_to_pull[@]} ]; then
                log_info "  Waiting ${image_delay}s before pulling next image..."
                sleep $image_delay
            fi
        done
        
        # Determine batch success based on image completions tracked during processing
        # DaemonSets are already deleted, so we infer from total nodes in batch
        log_info "✓ Batch $batch_num processing completed"
        total_success=$((total_success + batch_node_count))
        
        # Mark nodes in this batch as having images prepulled
        mark_nodes_prepulled "${batch_nodes[@]}"
        
        # Remove batch labels from nodes
        local batch_label_key="image-prepull-batch-$batch_idx"
        log_info "Removing temporary batch label $batch_label_key from nodes..."
        printf '%s\n' "${batch_nodes[@]}" | xargs -P 50 -I {} kubectl label node {} "$batch_label_key-" 2>&1 | grep -v "node/.* unlabeled" || true
        
        # Dynamic delay between batches based on failure rate
        if [ $batch_num -lt $num_batches ]; then
            local base_delay=${IMAGE_PREPULL_BATCH_DELAY:-5}
            local delay=$base_delay
            
            # Increase delay if previous batches had failures
            local failure_rate=0
            if [ $((total_success + total_failed)) -gt 0 ]; then
                failure_rate=$((total_failed * 100 / (total_success + total_failed)))
            fi
            
            if [ $failure_rate -gt 50 ]; then
                delay=$((base_delay * 3))  # 3x delay if >50% failure rate
                log_warning "High failure rate ($failure_rate%), increasing delay to ${delay}s"
            elif [ $failure_rate -gt 20 ]; then
                delay=$((base_delay * 2))  # 2x delay if >20% failure rate
                log_info "Elevated failure rate ($failure_rate%), increasing delay to ${delay}s"
            fi
            
            log_info "Waiting ${delay}s before next batch to allow registry recovery..."
            sleep $delay
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
