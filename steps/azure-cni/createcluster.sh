# #!/bin/bash

set -ex
RG=asn-$RUN_ID #Eastus2
CLUSTER="largeVSC"
# SUBSCRIPTION="TODO"
#K8S_VER=1.30
NODEPOOLS=1 # Per 500 nodes
NODEPOOL_SIZE=0
POD_IP_ALLOCATION_MODE="StaticBlock"

#az login
# create RG
echo "Create RG"
az group create --location $LOCATION --name $RG --tags SkipAutoDeleteTill=2032-12-31 skipGC="azure-cni-static-block perf" gc_skip="true"

# create vnet and subnets for azure cni static block
echo "create vnet and subnets for azure cni static block"
echo "create vnet"
vnetName="aksStaticBlock"
vnetAddressSpaceCIDR="10.0.0.0/8"

az network vnet create -n ${vnetName} -g ${RG} --address-prefixes ${vnetAddressSpaceCIDR} -l ${LOCATION}
echo "create vnet subnet"
vnetSubnetNameNodes="nodes"
vnetSubnetNamePods="pods"
vnetSubnetNodesCIDR="10.240.0.0/16"
vnetSubnetPodsCIDR="10.40.0.0/13"
az network vnet subnet create -n ${vnetSubnetNameNodes} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetNodesCIDR} -g ${RG}
az network vnet subnet create -n ${vnetSubnetNamePods} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetPodsCIDR} -g ${RG}

# create cluster
echo "create aks static block cluster"
vnetID=$(az network vnet list -g ${RG} | jq -r '.[].id')
nodeSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNameNodes}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNamePods}']" | jq -r '.[].id')
az aks create -n ${CLUSTER} -g ${RG} \
        -s Standard_D8_v3 -c 5 \
        --os-sku Ubuntu \
        -l ${LOCATION} \
        --network-plugin azure \
        --tier standard \
        --vnet-subnet-id ${nodeSubnetID} \
        --pod-subnet-id ${podSubnetID} \
        --pod-ip-allocation-mode $POD_IP_ALLOCATION_MODE \
        --vm-set-type VirtualMachineScaleSets \
        --tags run_id=${RG} role=slo \
        --load-balancer-backend-pool-type nodeIP \
        --no-ssh-key \
        --node-resource-group MC_vscperf-$RG-$CLUSTER \
        --max-pods 110 \
        --yes

VSC_CLUSTER_RESOURCE_ID=$(az group show -n MC_vscperf-$RG-$CLUSTER -o tsv --query id)
az tag update --resource-id $VSC_CLUSTER_RESOURCE_ID --operation Merge --tags SkipAutoDeleteTill=2032-12-31 skipGC="azure-cni-static-block perf" gc_skip="true"

# create usernodepools

for i in $(seq 1 ${NODEPOOLS}); do
    for attempt in $(seq 1 5); do
        echo "creating usernodepools: $attempt/15"
        az aks nodepool add --cluster-name ${CLUSTER} --name "userpool${i}" --resource-group ${RG} -s Standard_D4_v3 --os-sku Ubuntu --labels slo=true testscenario=cnivsc --node-taints "slo=true:NoSchedule" --vnet-subnet-id ${nodeSubnetID} --pod-subnet-id ${podSubnetID} --pod-ip-allocation-mode $POD_IP_ALLOCATION_MODE --max-pods 110 && break || echo "usernodepool creation attemped failed"
        sleep 60
    done
done 

for i in $(seq 1 ${NODEPOOLS}); do
    az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool${i}"
done

# # add prometheus nodepool
# export vnetGuid=$(az network vnet show --name $custVnetName --resource-group $RG --query resourceGuid --output tsv)
# export subnetResourceId=$(az network vnet subnet show --name $custSubnetName --vnet-name $custVnetName --resource-group $RG --query id --output tsv)
# export subnetGUID=$(az rest --method get --url "/subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/delgpod?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')


while true; do
STATUS=$(az aks show --name $CLUSTER --resource-group $RG --query "provisioningState" --output tsv)

    if [[ $STATUS == "Succeeded" ]]; then
        echo "Cluster is ready"
        break
    else
        sleep 30
    fi
done

for attempt in $(seq 1 5); do
    echo "creating prom nodepool: $attempt/15"
    az aks nodepool add --cluster-name ${CLUSTER} --name promnodepool --resource-group ${RG} -c 1 -s Standard_D64_v3 --os-sku Ubuntu --labels prometheus=true --vnet-subnet-id ${nodeSubnetID} --pod-subnet-id ${podSubnetID} --pod-ip-allocation-mode $POD_IP_ALLOCATION_MODE --max-pods 110 && break || echo "prometheus nodepool creation attemped failed"
    sleep 60
done

az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name promnodepool
az aks get-credentials -n ${CLUSTER} -g ${RG} --admin

# envsubst < swiftv2kubeobjects/pn.yaml | kubectl apply -f -

# sleep 60

# if kubectl get pn pn100 -o yaml | grep 'status: Ready' > /dev/null; then
#     echo "PN is ready"
# else
#     exit 1
# fi