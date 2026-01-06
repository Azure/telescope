#!/bin/bash
set -euo pipefail

# Pre-pull Container Images on Labeled Nodes
# This script creates DaemonSets to pull container images on all nodes labeled with swiftv2slo=true
# to reduce pod startup time during tests.
#
# Required Environment Variables:
# - DATAPATH_REPORTER_IMAGE (optional): Reporter image to pre-pull
# - NETSHOOT_IMAGE (optional): Netshoot image to pre-pull

# Source required libraries
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$SCRIPT_DIR/aks-utils.sh"

DAEMONSET_TEMPLATE="$SCRIPT_DIR/prepull-daemonset-template.yaml"

# Pre-pull container images on all labeled nodes to reduce startup time
function prepull_images_on_nodes() {
    local images_to_pull=("$@")
    
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
    
    # Create a temporary namespace for pre-pull operations
    local prepull_ns="image-prepull-$$"
    log_info "Creating namespace '$prepull_ns' for pre-pull operations..."
    kubectl create namespace "$prepull_ns" 2>/dev/null || true
    
    # Create DaemonSet for each image to ensure it's pulled on all nodes
    for img in "${images_to_pull[@]}"; do
        # Sanitize image name for k8s resource naming
        local ds_name="prepull-$(echo "$img" | sed 's|[^a-zA-Z0-9-]|-|g' | cut -c1-50)"
        local img_hash=$(echo "$img" | md5sum | cut -c1-8)
        
        log_info "Creating DaemonSet '$ds_name' to pull image '$img'..."
        
        # Generate DaemonSet from template
        # IMPORTANT: Replace NAMESPACE before NAME to avoid substring collision
        sed -e "s|IMAGE_PREPULL_NAMESPACE|$prepull_ns|g" \
            -e "s|IMAGE_PREPULL_NAME|$ds_name|g" \
            -e "s|IMAGE_HASH|$img_hash|g" \
            -e "s|IMAGE_TO_PULL|$img|g" \
            "$DAEMONSET_TEMPLATE" | kubectl apply -f -
        
        if [ $? -eq 0 ]; then
            log_info "  ✓ DaemonSet '$ds_name' created successfully"
        else
            log_warning "  ✗ Failed to create DaemonSet '$ds_name'"
        fi
    done
    
    # Wait for all DaemonSets to complete (all pods ready)
    log_info "Waiting for image pre-pull DaemonSets to complete..."
    local max_wait=600  # 10 minutes
    local elapsed=0
    local check_interval=10
    
    while [ $elapsed -lt $max_wait ]; do
        local all_ready=true
        local total_desired=0
        local total_ready=0
        
        for img in "${images_to_pull[@]}"; do
            local ds_name="prepull-$(echo "$img" | sed 's|[^a-zA-Z0-9-]|-|g' | cut -c1-50)"
            local ds_info
            ds_info=$(kubectl get daemonset "$ds_name" -n "$prepull_ns" -o json 2>/dev/null || echo "{}")
            
            local desired=$(echo "$ds_info" | jq -r '.status.desiredNumberScheduled // 0')
            local ready=$(echo "$ds_info" | jq -r '.status.numberReady // 0')
            
            total_desired=$((total_desired + desired))
            total_ready=$((total_ready + ready))
            
            if [ "$ready" -ne "$desired" ]; then
                all_ready=false
            fi
        done
        
        if [ "$all_ready" = true ] && [ $total_desired -gt 0 ]; then
            log_info "✓ All image pre-pull operations completed successfully ($total_ready/$total_desired pods ready)"
            break
        fi
        
        if [ $((elapsed % 30)) -eq 0 ]; then
            log_info "Image pre-pull progress: $total_ready/$total_desired pods ready (elapsed: ${elapsed}s)"
        fi
        
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    if [ $elapsed -ge $max_wait ]; then
        log_warning "Image pre-pull timed out after $((max_wait / 60)) minutes, but continuing..."
    fi
    
    # Cleanup: Delete the DaemonSets and namespace
    log_info "Cleaning up image pre-pull resources..."
    kubectl delete namespace "$prepull_ns" --wait=false >/dev/null 2>&1 || true
    
    log_info "Image pre-pull operation completed"
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
    
    if [ -n "${NETSHOOT_IMAGE:-}" ]; then
        images_to_prepull+=("$NETSHOOT_IMAGE")
        log_info "  NETSHOOT_IMAGE: $NETSHOOT_IMAGE"
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
