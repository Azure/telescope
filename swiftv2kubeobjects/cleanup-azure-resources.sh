#!/bin/bash
# NOTE: This script is designed to be resilient - it will continue on errors
# since this is a cleanup script and we want to attempt all cleanup steps.
# We use 'set +e' to prevent the script from exiting on failures.
set +e

# =============================================================================
# Cleanup script for Azure resources before resource group deletion
# This script:
# 1. Deletes AKS clusters and waits for completion
# 2. Removes NAT Gateway and NSG associations from subnets
# 3. Deletes NAT Gateways, NSGs, and Public IPs
#
# Environment variables:
#   RG or RESOURCE_GROUP_NAME - Resource group name (required)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "${SCRIPT_DIR}/lib/common.sh"

# Configuration
RG="${RG:-${RESOURCE_GROUP_NAME:-}}"

# Validate required inputs
if [[ -z "$RG" ]]; then
    echo "ERROR: RG or RESOURCE_GROUP_NAME environment variable is required"
    exit 1
fi

if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    echo "ERROR: AZURE_SUBSCRIPTION_ID environment variable is required"
    exit 1
fi

# Set the Azure subscription
echo "Setting Azure subscription to: $AZURE_SUBSCRIPTION_ID"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"

# NOTE: We intentionally do NOT trap SIGTERM/SIGINT here.
# This cleanup script should run to completion even if the pipeline is cancelled,
# as it helps free up resources.

# =============================================================================
# MAIN CLEANUP
# =============================================================================

echo "==================================================================="
echo "Force cleanup Azure resources in $RG before resource group deletion"
echo "==================================================================="

# =============================================================================
# STEP 1: DELETE AKS CLUSTERS
# =============================================================================
echo ""
echo "Deleting AKS clusters..."
echo "Listing clusters in resource group: $RG"
cluster_list=$(az aks list -g "$RG" --query "[].name" -o tsv 2>&1) || true
echo "Cluster list result: '$cluster_list'"

if [[ -z "$cluster_list" ]]; then
    echo "WARNING: No AKS clusters found in resource group $RG"
else
    for cluster in $cluster_list; do
        echo "Deleting AKS cluster: $cluster (this may take several minutes for large clusters)"
        retry_command 5 30 "az aks delete -g $RG -n $cluster --yes --no-wait" || true

        # Wait for cluster deletion to complete
        wait_for_cluster_deletion "$cluster" "$RG" 3600 || true
    done
fi

# Brief wait for managed resource group cleanup to propagate
echo "Waiting 60 seconds for managed resource group cleanup to propagate..."
sleep 60

# =============================================================================
# STEP 2: REMOVE NAT GATEWAY ASSOCIATIONS
# =============================================================================
echo ""
echo "Removing NAT Gateway associations..."
for vnet in $(az network vnet list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true); do
    for subnet in $(az network vnet subnet list -g "$RG" --vnet-name "$vnet" --query "[?natGateway].name" -o tsv 2>/dev/null || true); do
        echo "Removing NAT Gateway from subnet: $vnet/$subnet"
        retry_command 5 30 "az network vnet subnet update -g $RG --vnet-name $vnet -n $subnet --remove natGateway" || true
    done
done

# =============================================================================
# STEP 3: REMOVE NSG ASSOCIATIONS
# =============================================================================
echo ""
echo "Removing NSG associations..."
for vnet in $(az network vnet list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true); do
    for subnet in $(az network vnet subnet list -g "$RG" --vnet-name "$vnet" --query "[?networkSecurityGroup].name" -o tsv 2>/dev/null || true); do
        echo "Removing NSG from subnet: $vnet/$subnet"
        retry_command 5 30 "az network vnet subnet update -g $RG --vnet-name $vnet -n $subnet --remove networkSecurityGroup" || true
    done
done

# =============================================================================
# STEP 4: DELETE NAT GATEWAYS
# =============================================================================
echo ""
echo "Deleting NAT Gateways..."
for natgw in $(az network nat gateway list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true); do
    echo "Deleting NAT Gateway: $natgw"
    retry_command 5 30 "az network nat gateway delete -g $RG -n $natgw" || true
done

# =============================================================================
# STEP 5: DELETE NSGs
# =============================================================================
echo ""
echo "Deleting Network Security Groups..."
for nsg in $(az network nsg list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true); do
    echo "Deleting NSG: $nsg"
    retry_command 5 30 "az network nsg delete -g $RG -n $nsg" || true
done

# =============================================================================
# STEP 6: DELETE PUBLIC IPs
# =============================================================================
echo ""
echo "Deleting Public IP addresses..."
for pip in $(az network public-ip list -g "$RG" --query "[].name" -o tsv 2>/dev/null || true); do
    echo "Deleting Public IP: $pip"
    retry_command 5 30 "az network public-ip delete -g $RG -n $pip" || true
done

echo ""
echo "==================================================================="
echo "Pre-cleanup completed"
echo "==================================================================="

# Always exit with 0 - this is a cleanup script and we want subsequent steps to run
exit 0