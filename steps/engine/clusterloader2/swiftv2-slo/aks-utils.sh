#!/bin/bash

# AKS Utilities Library
# Contains common functions for AKS cluster management, logging, and nodepool operations

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
    
    # Use SHARED_RUN_ID for cluster discovery when reusing, otherwise use RUN_ID
    local cluster_run_id="${SHARED_RUN_ID:-$RUN_ID}"
    
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
