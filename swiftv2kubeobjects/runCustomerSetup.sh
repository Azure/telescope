#!/bin/bash
# This script is manually from devbox since this is not required for every run.
# Make sure to update the variables below as per your requirements 
# Make sure jq is installed on your devbox
# Usage:
# az login --use-device-code
# cd to current folder
# chmod +x runCustomerSetup.sh
# ./runCustomerSetup.sh

set -ex
sub=9b8218f9-902a-4d20-a65c-e98acec5362f
RG="sv2-perf-infra-customer"
CLUSTER="ping-target"
LOCATION="eastus2euap"

# create RG
echo "Create RG"
date=$(date -d "+3 month" +"%Y-%m-%d")
az group create --location $LOCATION --name $RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

# create customer vnet
custVnetName=custvnet
custScaleDelSubnet="scaledel"
custAKSNodeSubnet="aksnodes"
custAKSPodSubnet="akspods"
custVnetAddressSpaceCIDR="172.16.0.0/12"
custScaleDelSubnetCIDR="172.26.0.0/16"
custAKSNodeSubnetCIDR="172.27.0.0/24"
custAKSPodSubnetCIDR="172.27.1.0/24"

az network vnet create -n ${custVnetName} -g ${RG} --address-prefixes ${custVnetAddressSpaceCIDR} -l ${LOCATION} -o none
az network vnet subnet create --resource-group $RG --vnet-name $custVnetName --name $custScaleDelSubnet --address-prefixes $custScaleDelSubnetCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
for attempt in $(seq 1 5); do
    echo "Attempting to delegate $custScaleDelSubnet using subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F$sub%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$custVnetName%2Fsubnets%2F$custScaleDelSubnet'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

az network vnet subnet create \
  --resource-group $RG \
  --vnet-name $custVnetName \
  --name $custAKSNodeSubnet \
  --address-prefixes $custAKSNodeSubnetCIDR -o none
az network vnet subnet create \
  --resource-group $RG \
  --vnet-name $custVnetName \
  --name $custAKSPodSubnet \
  --address-prefixes $custAKSPodSubnetCIDR \
  --delegations Microsoft.ContainerService/managedClusters -o none

# create cluster
echo "create cluster"
nodeSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${custVnetName} --query "[?name=='${custAKSNodeSubnet}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${custVnetName} --query "[?name=='${custAKSPodSubnet}']" | jq -r '.[].id')
nodeRGName=MC_$RG-$CLUSTER-$LOCATION
az aks create --name $CLUSTER \
        -g $RG \
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

echo "Deploy nginx pod on the cluster with IP - 172.27.0.30"
az aks get-credentials --resource-group $RG --name $CLUSTER --overwrite-existing -a
kubectl apply -f ./nginx-deployment.yaml

# print vnet guid, subnet guid of scaledel and subnet id of scaledel
echo "=== Network Information ==="

# Get VNet GUID (try different properties)
vnetGuid=$(az network vnet show --resource-group $RG --name $custVnetName --query "resourceGuid" -o tsv 2>/dev/null || echo "Not available")

# Get subnet info and extract GUID and ID
subnetInfo=$(az rest --method get --url "/subscriptions/$sub/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/$custScaleDelSubnet?api-version=2023-06-01")
subnetGuid=$(echo $subnetInfo | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')
subnetId=$(echo $subnetInfo | jq -r '.id')

echo "VNet GUID: $vnetGuid"
echo "ScaleDel Subnet GUID: $subnetGuid"
echo "ScaleDel Subnet ID: $subnetId"