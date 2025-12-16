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

export SETUP_ACR_AND_MI=true
export CLUSTER="ping-target"

# create RG
echo "Create RG"
export date=$(date -d "+3 month" +"%Y-%m-%d")
az account set -s $CUST_SUB
az group create --location $LOCATION --name $CUST_RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

# create customer vnet
export custAKSNodeSubnet="aksnodes"
export custAKSPodSubnet="akspods"
export custVnetAddressSpaceCIDR="172.16.0.0/12"
export custScaleDelSubnetCIDR="172.26.0.0/16"
export custAKSNodeSubnetCIDR="172.27.0.0/24"
export custAKSPodSubnetCIDR="172.27.1.0/24"

az network vnet create -n ${CUST_VNET_NAME} -g $CUST_RG --address-prefixes ${custVnetAddressSpaceCIDR} -l ${LOCATION} -o none
az network vnet subnet create --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $CUST_SCALE_DEL_SUBNET --address-prefixes $custScaleDelSubnetCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
az account set -s $SD_SUB
for attempt in $(seq 1 5); do
    echo "Attempting to delegate $CUST_SCALE_DEL_SUBNET using subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F$CUST_SUB%2FresourceGroups%2F$CUST_RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$CUST_VNET_NAME%2Fsubnets%2F$CUST_SCALE_DEL_SUBNET'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

az account set -s $CUST_SUB
export custVnetGUID=$(az network vnet show --name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query resourceGuid --output tsv)
export custSubnetResourceId=$(az network vnet subnet show --name ${CUST_SCALE_DEL_SUBNET} --vnet-name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query id --output tsv)
export custSubnetGUID=$(az rest --method get --url "/subscriptions/${CUST_SUB}/resourceGroups/${CUST_RG}/providers/Microsoft.Network/virtualNetworks/${CUST_VNET_NAME}/subnets/${CUST_SCALE_DEL_SUBNET}?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

echo "VNet GUID: $custVnetGUID"
echo "Subnet Resource ID: $custSubnetResourceId"
echo "Subnet GUID: $custSubnetGUID"

az network vnet subnet create \
  --resource-group $CUST_RG \
  --vnet-name $CUST_VNET_NAME \
  --name $custAKSNodeSubnet \
  --address-prefixes $custAKSNodeSubnetCIDR -o none
az network vnet subnet create \
  --resource-group $CUST_RG \
  --vnet-name $CUST_VNET_NAME \
  --name $custAKSPodSubnet \
  --address-prefixes $custAKSPodSubnetCIDR \
  --delegations Microsoft.ContainerService/managedClusters -o none

# create cluster
echo "create cluster"
export nodeSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSNodeSubnet}']" | jq -r '.[].id')
export podSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSPodSubnet}']" | jq -r '.[].id')
export nodeRGName=MC_$CUST_RG-$CLUSTER-$LOCATION
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

echo "Prevent autodeletion of cluster resources"
export Node_RG_ID=$(az group show -n $nodeRGName -o tsv --query id)
export Node_RG_ID=${Node_RG_ID//$'\r'}
az tag update --resource-id $Node_RG_ID --operation Merge --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

echo "Deploy nginx pod on the cluster with IP - 172.27.0.30"
az aks get-credentials --resource-group $CUST_RG --name $CLUSTER --overwrite-existing -a
kubectl apply -f ./nginx-deployment.yaml

if [ "$SETUP_ACR_AND_MI" != "true" ]; then
  echo "Skipping ACR and MI setup as SETUP_ACR_AND_MI is not set to true"
  exit 0
fi
export ACR_NAME="sv2perfacr$LOCATION"
export IMAGE_NAME="nicolaka/netshoot"
export ACR_IMAGE_NAME="netshoot:latest"
export SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
export SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"

az acr create --resource-group $CUST_RG --name $ACR_NAME --sku Basic
az acr login --name $ACR_NAME
docker pull $IMAGE_NAME
docker tag $IMAGE_NAME $ACR_NAME.azurecr.io/$ACR_IMAGE_NAME
docker push $ACR_NAME.azurecr.io/$ACR_IMAGE_NAME
echo "Docker image $IMAGE_NAME mirrored to ACR $ACR_NAME as $ACR_IMAGE_NAME"
echo "You can now use this image in your AKS cluster."

az identity create \
  --name $SHARED_KUBELET_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --location $LOCATION

export pId=$(az identity show \
  --name $SHARED_KUBELET_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

az role assignment create \
  --assignee-object-id $pId \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope $(az acr show --name $ACR_NAME --query id -o tsv)

az identity create \
  --name $SHARED_CONTROL_PLANE_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --location $LOCATION 

export cPID=$(az identity show \
  --name $SHARED_CONTROL_PLANE_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

az role assignment create \
  --assignee-object-id $cPID \
  --assignee-principal-type ServicePrincipal \
  --role "Managed Identity Operator" \
  --scope /subscriptions/$CUST_SUB/resourcegroups/$CUST_RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$SHARED_KUBELET_IDENTITY_NAME

