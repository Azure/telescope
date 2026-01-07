#!/bin/bash
# This script is manually from devbox since this is not required for every run.

# Prerequisites:
# Make sure you have the Azure CLI installed and you're logged in.
# Make sure you have Docker installed and running.
# Make sure you have kubectl installed. 
# Make sure jq is installed on your devbox

# Usage:
# Update the variables in shared-config.sh as per your requirements (location, subscription, etc.)
# cd to current folder
# chmod +x runCustomerSetup.sh
# chmod +x shared-config.sh
# ./runCustomerSetup.sh

set -ex

# Source shared configuration if available

echo "Loading shared configuration..."
source "$(dirname "$0")/shared-config.sh"

export CLUSTER="ping-target"

# create RG
echo "Create RG"
export date=$(date -d "+3 month" +"%Y-%m-%d")
az account set -s $CUST_SUB

if az group exists --name $CUST_RG | grep -q "true"; then
  echo "Resource group $CUST_RG already exists, updating tags"
  az group update --name $CUST_RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"
else
  echo "Creating resource group $CUST_RG"
  az group create --location $LOCATION --name $CUST_RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"
fi

# create customer vnet
export custAKSNodeSubnet="aksnodes"
export custAKSPodSubnet="akspods"
export custVnetAddressSpaceCIDR="172.16.0.0/12"
export custScaleDelSubnetCIDR="172.26.0.0/16"
export custAKSNodeSubnetCIDR="172.27.0.0/24"
export custAKSPodSubnetCIDR="172.27.1.0/24"

if az network vnet show -n ${CUST_VNET_NAME} -g $CUST_RG &>/dev/null; then
  echo "VNet ${CUST_VNET_NAME} already exists"
else
  echo "Creating VNet ${CUST_VNET_NAME}"
  az network vnet create -n ${CUST_VNET_NAME} -g $CUST_RG --address-prefixes ${custVnetAddressSpaceCIDR} -l ${LOCATION} -o none
fi

if az network vnet subnet show --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $CUST_SCALE_DEL_SUBNET &>/dev/null; then
  echo "Subnet $CUST_SCALE_DEL_SUBNET already exists"
else
  echo "Creating subnet $CUST_SCALE_DEL_SUBNET"
  az network vnet subnet create --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $CUST_SCALE_DEL_SUBNET --address-prefixes $custScaleDelSubnetCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
fi

# Check if subnet is already delegated
export custSubnetInfo=$(az rest --method get --url "/subscriptions/${CUST_SUB}/resourceGroups/${CUST_RG}/providers/Microsoft.Network/virtualNetworks/${CUST_VNET_NAME}/subnets/${CUST_SCALE_DEL_SUBNET}?api-version=2024-05-01" 2>/dev/null || echo "{}")
export custSubnetGUID=$(echo "$custSubnetInfo" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId // empty')

if [ -z "$custSubnetGUID" ] || [ "$custSubnetGUID" == "null" ]; then
  echo "Subnet $CUST_SCALE_DEL_SUBNET is not delegated, delegating now..."
  az account set -s $SD_SUB
  for attempt in $(seq 1 5); do
      echo "Attempting to delegate $CUST_SCALE_DEL_SUBNET using subnetdelegator command: $attempt/5"
      script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F$CUST_SUB%2FresourceGroups%2F$CUST_RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$CUST_VNET_NAME%2Fsubnets%2F$CUST_SCALE_DEL_SUBNET'" /dev/null && break || echo "Command failed, retrying..."
      sleep 30
  done
  az account set -s $CUST_SUB
  # Re-fetch subnet info after delegation
  export custSubnetInfo=$(az rest --method get --url "/subscriptions/${CUST_SUB}/resourceGroups/${CUST_RG}/providers/Microsoft.Network/virtualNetworks/${CUST_VNET_NAME}/subnets/${CUST_SCALE_DEL_SUBNET}?api-version=2024-05-01")
  export custSubnetGUID=$(echo "$custSubnetInfo" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')
else
  echo "Subnet $CUST_SCALE_DEL_SUBNET is already delegated (GUID: $custSubnetGUID)"
  az account set -s $CUST_SUB
fi
export custVnetGUID=$(az network vnet show --name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query resourceGuid --output tsv)
export custSubnetResourceId=$(az network vnet subnet show --name ${CUST_SCALE_DEL_SUBNET} --vnet-name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query id --output tsv)

echo "VNet GUID: $custVnetGUID"
echo "Subnet Resource ID: $custSubnetResourceId"
echo "Subnet GUID: $custSubnetGUID"

if az network vnet subnet show --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $custAKSNodeSubnet &>/dev/null; then
  echo "Subnet $custAKSNodeSubnet already exists"
else
  echo "Creating subnet $custAKSNodeSubnet"
  az network vnet subnet create \
    --resource-group $CUST_RG \
    --vnet-name $CUST_VNET_NAME \
    --name $custAKSNodeSubnet \
    --address-prefixes $custAKSNodeSubnetCIDR -o none
fi

if az network vnet subnet show --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $custAKSPodSubnet &>/dev/null; then
  echo "Subnet $custAKSPodSubnet already exists"
else
  echo "Creating subnet $custAKSPodSubnet"
  az network vnet subnet create \
    --resource-group $CUST_RG \
    --vnet-name $CUST_VNET_NAME \
    --name $custAKSPodSubnet \
    --address-prefixes $custAKSPodSubnetCIDR \
    --delegations Microsoft.ContainerService/managedClusters -o none
fi

# create cluster
echo "create cluster"
export nodeSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSNodeSubnet}']" | jq -r '.[].id')
export podSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSPodSubnet}']" | jq -r '.[].id')
export nodeRGName=MC_$CUST_RG-$CLUSTER-$LOCATION

if az aks show --name $CLUSTER -g $CUST_RG &>/dev/null; then
  echo "AKS cluster $CLUSTER already exists"
else
  echo "Creating AKS cluster $CLUSTER"
  az aks create --name $CLUSTER \
          -g $CUST_RG \
          -l $LOCATION \
          --max-pods 250 \
          --node-count 2 \
          --network-plugin azure \
          --node-vm-size Standard_D4_v3 \
          --node-os-upgrade-channel NodeImage \
          --vnet-subnet-id $nodeSubnetID \
          --pod-subnet-id $podSubnetID \
          --node-resource-group $nodeRGName
fi

echo "Prevent autodeletion of cluster resources"
export Node_RG_ID=$(az group show -n $nodeRGName -o tsv --query id)
export Node_RG_ID=${Node_RG_ID//$'\r'}
az tag update --resource-id $Node_RG_ID --operation Merge --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

echo "Grant Network Contributor role to cluster control plane identity on VNet"
export CLUSTER_IDENTITY_OBJECT_ID=$(az aks show --name $CLUSTER --resource-group $CUST_RG --query identity.principalId --output tsv)
export VNET_RESOURCE_ID=$(az network vnet show --name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query id --output tsv)

if az role assignment list --assignee $CLUSTER_IDENTITY_OBJECT_ID --scope $VNET_RESOURCE_ID --role "Network Contributor" | jq -e 'length > 0' &>/dev/null; then
  echo "Network Contributor role assignment already exists for cluster identity"
else
  echo "Creating Network Contributor role assignment for cluster identity on VNet"
  az role assignment create \
    --assignee-object-id $CLUSTER_IDENTITY_OBJECT_ID \
    --assignee-principal-type ServicePrincipal \
    --role "Network Contributor" \
    --scope $VNET_RESOURCE_ID
fi

echo "Deploy nginx pod on the cluster with IP - 172.27.0.30"
az aks get-credentials --resource-group $CUST_RG --name $CLUSTER --overwrite-existing -a

if kubectl get deployment nginx-deployment &>/dev/null; then
  echo "nginx-deployment already exists, skipping"
else
  echo "Applying nginx-deployment.yaml"
  kubectl apply -f ./nginx-deployment.yaml
fi

# =============================================================================
# CREATE SHARED MANAGED IDENTITIES
# =============================================================================
echo "Setting up shared managed identities..."

# Create kubelet identity
if az identity show --name $SHARED_KUBELET_IDENTITY_NAME --resource-group $CUST_RG &>/dev/null; then
  echo "Managed identity $SHARED_KUBELET_IDENTITY_NAME already exists"
else
  echo "Creating managed identity $SHARED_KUBELET_IDENTITY_NAME"
  az identity create \
    --name $SHARED_KUBELET_IDENTITY_NAME \
    --resource-group $CUST_RG \
    --location $LOCATION
  echo "Waiting for identity to propagate..."
  sleep 10
fi

export pId=$(az identity show \
  --name $SHARED_KUBELET_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

# Note: AcrPull permissions are granted in setup-regional-acr.sh
# This keeps identity creation separate from ACR setup

# Create control plane identity
if az identity show --name $SHARED_CONTROL_PLANE_IDENTITY_NAME --resource-group $CUST_RG &>/dev/null; then
  echo "Managed identity $SHARED_CONTROL_PLANE_IDENTITY_NAME already exists"
else
  echo "Creating managed identity $SHARED_CONTROL_PLANE_IDENTITY_NAME"
  az identity create \
    --name $SHARED_CONTROL_PLANE_IDENTITY_NAME \
    --resource-group $CUST_RG \
    --location $LOCATION
  echo "Waiting for identity to propagate..."
  sleep 10
fi

export cPID=$(az identity show \
  --name $SHARED_CONTROL_PLANE_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

export kubeletIdentityScope=/subscriptions/$CUST_SUB/resourcegroups/$CUST_RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$SHARED_KUBELET_IDENTITY_NAME

# Grant Managed Identity Operator role to control plane identity
if az role assignment list --assignee $cPID --scope $kubeletIdentityScope --role "Managed Identity Operator" | jq -e 'length > 0' &>/dev/null; then
  echo "Managed Identity Operator role assignment already exists"
else
  echo "Creating Managed Identity Operator role assignment"
  az role assignment create \
    --assignee-object-id $cPID \
    --assignee-principal-type ServicePrincipal \
    --role "Managed Identity Operator" \
    --scope $kubeletIdentityScope
fi

echo "Shared managed identities created successfully!"
echo "These identities will be used by all AKS clusters created via createclusterforping.sh"
echo ""
echo "IMPORTANT: Run './setup-regional-acr.sh' next to:"
echo "  1. Create regional ACR: $REGIONAL_ACR_NAME"
echo "  2. Mirror images from source ACR"
echo "  3. Grant ACR permissions to kubelet identity"

