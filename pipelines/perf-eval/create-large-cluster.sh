#!/bin/bash

set -ex
RG="$USER-cilscale-$RANDOM-$(date +"%Y%m%d%H%M%S")"
CLUSTER="large"
SUBSCRIPTION="TODO"
LOCATION=eastus2
K8S_VER=1.29
NODEPOOLS=2 # Per 500 nodes
NODEPOOL_SIZE=0

# az login
# create RG
echo "Create RG"
az group create --location $LOCATION --name $RG

# create vnetsubnets for overlay
echo "create vnet subnets for overlay"
echo "create vnet"
vnetName="net"
vnetAddressSpaceCIDR="10.0.0.0/9"

az network vnet create -n ${vnetName} -g ${RG} --address-prefixes ${vnetAddressSpaceCIDR} -l ${LOCATION}
echo "create vnet subnet"
vnetSubnetNameNodes="nodes"
vnetSubnetNodesCIDR="10.0.0.0/16"
podCIDR="10.128.0.0/9"
az network vnet subnet create -n ${vnetSubnetNameNodes} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetNodesCIDR} -g ${RG}

# create cluster
echo "create cluster"
vnetID=$(az network vnet list -g ${RG} | jq -r '.[].id')
subnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} | jq -r '.[].id')
az aks create -n ${CLUSTER} -g ${RG} \
        -s Standard_D8_v3 -c 5 \
        --os-sku Ubuntu \
        -l ${LOCATION} --max-pods 110 \
        --service-cidr 192.168.0.0/16 --dns-service-ip 192.168.0.10 \
        --network-plugin azure \
        --network-dataplane cilium \
        --tier standard \
        --kubernetes-version ${K8S_VER} \
        --network-plugin-mode overlay --vnet-subnet-id ${subnetID} \
        --pod-cidr ${podCIDR} \
        --vm-set-type VirtualMachineScaleSets \
        --tags run_id=${RG} role=ces \
        --no-ssh-key \
        --yes

# create nodepools
for i in $(seq 1 ${NODEPOOLS}); do
        az aks nodepool add --cluster-name ${CLUSTER} --name "nodepool0${i}" --resource-group ${RG} -c 10 --max-pods 110 -s Standard_D4_v3 --os-sku Ubuntu --vm-set-type VirtualMachineScaleSets --labels slo=true --node-taints "slo=true:NoSchedule"
        sleep 60
done

# scale nodepools
for i in $(seq 1 ${NODEPOOLS}); do
        az aks nodepool scale --cluster-name ${CLUSTER} --name "nodepool0${i}" --resource-group ${RG} -c ${NODEPOOL_SIZE}
        sleep 300
done

# uncomment if using for 'cluster churn' scenario
# for i in $(seq 1 ${NODEPOOLS}); do
#         az aks nodepool update --cluster-name ${CLUSTER} --name "nodepool0${i}" --resource-group ${RG} --enable-cluster-autoscaler --min-count 0 --max-count 500
# done

# add prometheus nodepool
az aks nodepool add --cluster-name ${CLUSTER} --name promnodepool --resource-group ${RG} -c 1 -s Standard_D64_v3 --os-sku Ubuntu --labels prometheus=true