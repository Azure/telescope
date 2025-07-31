#!/bin/bash
# This script deletes all resources created by runCustomerSetup.sh
# This is intended to be run manually from devbox when customer setup cleanup is needed
# Usage:
# az login --use-device-code
# cd to current folder
# chmod +x deleteCustomerSetup.sh
# ./deleteCustomerSetup.sh

set -ex

# Variables - should match those in runCustomerSetup.sh
sub=9b8218f9-902a-4d20-a65c-e98acec5362f
RG="sv2-perf-infra-customer"
CLUSTER="ping-target"
LOCATION="eastus2euap"

# Customer VNet configuration
custVnetName=custvnet
custScaleDelSubnet="scaledel"
custAKSNodeSubnet="aksnodes"
custAKSPodSubnet="akspods"

# Managed cluster resource group name
nodeRGName=MC_$RG-$CLUSTER-$LOCATION

# Function to safely delete a resource with retry logic
safe_delete() {
    local resource_type=$1
    local resource_name=$2
    local resource_group=$3
    local additional_params=${4:-""}
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        if az $resource_type show --name "$resource_name" --resource-group "$resource_group" $additional_params &>/dev/null; then
            echo "Deleting $resource_type: $resource_name (attempt $((retry_count + 1))/$max_retries)"
            if az $resource_type delete --name "$resource_name" --resource-group "$resource_group" $additional_params --yes --no-wait 2>/dev/null; then
                echo "Delete command issued successfully for $resource_type: $resource_name"
                break
            else
                echo "Failed to delete $resource_type: $resource_name"
                retry_count=$((retry_count + 1))
                if [ $retry_count -lt $max_retries ]; then
                    echo "Retrying in 30 seconds..."
                    sleep 30
                fi
            fi
        else
            echo "$resource_type $resource_name does not exist or already deleted"
            break
        fi
    done
    
    if [ $retry_count -eq $max_retries ]; then
        echo "WARNING: Failed to delete $resource_type: $resource_name after $max_retries attempts"
    fi
}

# Function to wait for resource deletion
wait_for_deletion() {
    local resource_type=$1
    local resource_name=$2
    local resource_group=$3
    local additional_params=${4:-""}
    local timeout=${5:-600}  # Default 10 minutes
    local check_interval=30
    local elapsed=0
    
    echo "Waiting for $resource_type $resource_name to be fully deleted..."
    
    while [ $elapsed -lt $timeout ]; do
        if ! az $resource_type show --name "$resource_name" --resource-group "$resource_group" $additional_params &>/dev/null; then
            echo "$resource_type $resource_name has been successfully deleted"
            return 0
        fi
        
        echo "Still waiting for $resource_type $resource_name deletion... (elapsed: ${elapsed}s)"
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    echo "WARNING: Timeout waiting for $resource_type $resource_name deletion"
    return 1
}

echo "Starting cleanup of customer setup resources created by runCustomerSetup.sh"
echo "Resource Group: $RG"
echo "Cluster: $CLUSTER"
echo "Customer VNet: $custVnetName"

# Check if resource group exists
if ! az group show --name "$RG" &>/dev/null; then
    echo "Resource group $RG does not exist. Nothing to clean up."
    exit 0
fi

# Delete Kubernetes resources first (if cluster exists and is accessible)
echo "=== Cleaning up Kubernetes resources ==="
if az aks show --name "$CLUSTER" --resource-group "$RG" &>/dev/null; then
    echo "Getting AKS credentials for cleanup..."
    if az aks get-credentials --resource-group "$RG" --name "$CLUSTER" --overwrite-existing -a 2>/dev/null; then
        echo "Deleting nginx deployment..."
        kubectl delete -f ./nginx-deployment.yaml --ignore-not-found=true --timeout=60s 2>/dev/null || echo "Failed to delete nginx deployment or deployment not found"
        
        # Delete any other Kubernetes resources if needed
        echo "Waiting for Kubernetes resources to clean up..."
        sleep 30
    else
        echo "Could not get AKS credentials, skipping Kubernetes resource cleanup"
    fi
else
    echo "AKS cluster does not exist, skipping Kubernetes resource cleanup"
fi

# Delete AKS cluster
echo "=== Deleting AKS cluster ==="
safe_delete "aks" "$CLUSTER" "$RG"

# Wait for AKS cluster deletion to complete
wait_for_deletion "aks" "$CLUSTER" "$RG" "" 1800

# Delete the managed cluster resource group (created by AKS)
echo "=== Deleting managed cluster resource group ==="
if az group show --name "$nodeRGName" &>/dev/null; then
    echo "Deleting managed cluster resource group: $nodeRGName"
    az group delete --name "$nodeRGName" --yes --no-wait
    echo "Managed cluster resource group deletion initiated"
else
    echo "Managed cluster resource group $nodeRGName does not exist or already deleted"
fi

# Clean up subnet delegations before deleting subnets
echo "=== Cleaning up subnet delegations ==="
if az network vnet subnet show --resource-group "$RG" --vnet-name "$custVnetName" --name "$custScaleDelSubnet" &>/dev/null; then
    echo "Attempting to clean up subnet delegation for $custScaleDelSubnet..."
    for attempt in $(seq 1 3); do
        echo "Attempting to remove delegation for $custScaleDelSubnet using subnetdelegator command: $attempt/3"
        script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X DELETE http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F$sub%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$custVnetName%2Fsubnets%2F$custScaleDelSubnet'" /dev/null && break || echo "Command failed, retrying..."
        sleep 30
    done
fi

# Delete VNet subnets in reverse order of creation
echo "=== Deleting VNet subnets ==="
safe_delete "network vnet subnet" "$custAKSPodSubnet" "$RG" "--vnet-name $custVnetName"
wait_for_deletion "network vnet subnet" "$custAKSPodSubnet" "$RG" "--vnet-name $custVnetName" 300

safe_delete "network vnet subnet" "$custAKSNodeSubnet" "$RG" "--vnet-name $custVnetName"
wait_for_deletion "network vnet subnet" "$custAKSNodeSubnet" "$RG" "--vnet-name $custVnetName" 300

safe_delete "network vnet subnet" "$custScaleDelSubnet" "$RG" "--vnet-name $custVnetName"
wait_for_deletion "network vnet subnet" "$custScaleDelSubnet" "$RG" "--vnet-name $custVnetName" 300

# Delete Customer VNet
echo "=== Deleting Customer VNet ==="
safe_delete "network vnet" "$custVnetName" "$RG"
wait_for_deletion "network vnet" "$custVnetName" "$RG" "" 300

# Final cleanup - delete the main resource group
echo "=== Deleting customer resource group ==="
echo "Waiting a bit before deleting the customer resource group to ensure all resources are cleaned up..."
sleep 60

if az group show --name "$RG" &>/dev/null; then
    echo "Deleting customer resource group: $RG"
    az group delete --name "$RG" --yes --no-wait
    echo "Customer resource group deletion initiated"
    
    # Optionally wait for resource group deletion
    echo "Waiting for customer resource group deletion to complete..."
    timeout=1800  # 30 minutes
    check_interval=60
    elapsed=0
    
    while [ $elapsed -lt $timeout ]; do
        if ! az group show --name "$RG" &>/dev/null; then
            echo "Customer resource group $RG has been successfully deleted"
            break
        fi
        
        echo "Still waiting for resource group $RG deletion... (elapsed: ${elapsed}s)"
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    if [ $elapsed -ge $timeout ]; then
        echo "WARNING: Timeout waiting for customer resource group deletion. Check Azure portal for status."
    fi
else
    echo "Customer resource group $RG does not exist or already deleted"
fi

echo "=== Cleanup Summary ==="
echo "The following customer setup resources have been scheduled for deletion:"
echo "- AKS Cluster: $CLUSTER"
echo "- Managed Cluster Resource Group: $nodeRGName"
echo "- Customer VNet Subnets: $custScaleDelSubnet, $custAKSNodeSubnet, $custAKSPodSubnet"
echo "- Customer VNet: $custVnetName"
echo "- Customer Resource Group: $RG"
echo "- Nginx Deployment (Kubernetes resource)"
echo ""
echo "Note: Some deletions may still be in progress. Check the Azure portal to confirm all resources have been removed."
echo ""
echo "Customer setup cleanup script completed!"
