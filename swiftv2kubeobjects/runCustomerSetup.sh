#!/bin/bash
# This script is manually from devbox since this is not required for every run.
# Make sure to update the variables in shared-config.sh as per your requirements 
# Make sure jq is installed on your devbox
# Usage:
# az login --use-device-code
# cd to current folder
# chmod +x runCustomerSetup.sh
# ./runCustomerSetup.sh

set -ex

# Source shared configuration if available
if [[ -f "$(dirname "$0")/shared-config.sh" ]]; then
    echo "Loading shared configuration..."
    source "$(dirname "$0")/shared-config.sh"
else
    # Fallback to direct configuration
    CUST_SUB=${SUBSCRIPTION:-9b8218f9-902a-4d20-a65c-e98acec5362f}
    LOCATION=${LOCATION:-"uksouth"}
    CUST_RG="sv2-perf-cust-$LOCATION"
    CUST_VNET_NAME=custvnet
    CUST_SCALE_DEL_SUBNET="scaledel"
    SETUP_ACR_AND_MI=true
    SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
    SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"
fi

CLUSTER="ping-target"

# create RG
echo "Create RG"
date=$(date -d "+3 month" +"%Y-%m-%d")
az account set -s $CUST_SUB
az group create --location $LOCATION --name $CUST_RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

# create customer vnet
custAKSNodeSubnet="aksnodes"
custAKSPodSubnet="akspods"
custVnetAddressSpaceCIDR="172.16.0.0/12"
custScaleDelSubnetCIDR="172.26.0.0/16"
custAKSNodeSubnetCIDR="172.27.0.0/24"
custAKSPodSubnetCIDR="172.27.1.0/24"

az network vnet create -n ${CUST_VNET_NAME} -g $CUST_RG --address-prefixes ${custVnetAddressSpaceCIDR} -l ${LOCATION} -o none
az network vnet subnet create --resource-group $CUST_RG --vnet-name $CUST_VNET_NAME --name $CUST_SCALE_DEL_SUBNET --address-prefixes $custScaleDelSubnetCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
for attempt in $(seq 1 5); do
    echo "Attempting to delegate $CUST_SCALE_DEL_SUBNET using subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F$CUST_SUB%2FresourceGroups%2F$CUST_RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$CUST_VNET_NAME%2Fsubnets%2F$CUST_SCALE_DEL_SUBNET'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

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
nodeSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSNodeSubnet}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g $CUST_RG --vnet-name ${CUST_VNET_NAME} --query "[?name=='${custAKSPodSubnet}']" | jq -r '.[].id')
nodeRGName=MC_$CUST_RG-$CLUSTER-$LOCATION
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
Node_RG_ID=$(az group show -n $nodeRGName -o tsv --query id)
Node_RG_ID=${Node_RG_ID//$'\r'}
az tag update --resource-id $Node_RG_ID --operation Merge --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

echo "Assign Network Contributor role to AKS cluster identity for load balancer operations"
AKS_CLUSTER_IDENTITY=$(az aks show --resource-group $CUST_RG --name $CLUSTER --query identity.principalId --output tsv)
az role assignment create --assignee $AKS_CLUSTER_IDENTITY --role "Network Contributor" --scope /subscriptions/$CUST_SUB/resourceGroups/$CUST_RG

echo "Deploy nginx pod on the cluster with IP - 172.27.0.30"
az aks get-credentials --resource-group $CUST_RG --name $CLUSTER --overwrite-existing -a
kubectl apply -f ./nginx-deployment.yaml

if [ "$SETUP_ACR_AND_MI" != "true" ]; then
  echo "Skipping ACR and MI setup as SETUP_ACR_AND_MI is not set to true"
  exit 0
fi
ACR_NAME="sv2perfacr$LOCATION"
IMAGE_NAME="nicolaka/netshoot"
ACR_IMAGE_NAME="netshoot:latest"
SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"

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

pId=$(az identity show \
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

cPID=$(az identity show \
  --name $SHARED_CONTROL_PLANE_IDENTITY_NAME \
  --resource-group $CUST_RG \
  --query principalId \
  --output tsv)

az role assignment create \
  --assignee-object-id $cPID \
  --assignee-principal-type ServicePrincipal \
  --role "Managed Identity Operator" \
  --scope /subscriptions/$CUST_SUB/resourcegroups/$CUST_RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$SHARED_KUBELET_IDENTITY_NAME

