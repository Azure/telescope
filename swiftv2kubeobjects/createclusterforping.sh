# #!/bin/bash

set -ex
#RG="$USER-swiftv2-$RANDOM-$(date +"%Y%m%d%H%M%S")"
RG=$RUN_ID #Eastus2
#RG=chlochen-swiftv2-scale-$LOCATION
CLUSTER="large"
SUBSCRIPTION="TODO"
K8S_VER=1.30
NODEPOOLS=1 # Per 500 nodes
NODEPOOL_SIZE=0

#az login
# create RG
echo "Create RG"
az group create --location $LOCATION --name $RG --tags SkipAutoDeleteTill=2032-12-31 skipGC="swift v2 perf" gc_skip="true"

# create user assigned NAT gateway
# echo "create public ips"
# for i in {1..5}; do
#        pipName="pip${i}"
#        az network public-ip create -n ${pipName} -g ${RG} -l ${LOCATION} --sku Standard
# done

# echo "create user assigned NAT gateway"
# res=$(az network public-ip list -g ${RG} -o json | jq -r '.[].ipAddress')
# ips=""
# for ip in ${res}; do
#        ips="${ips}${ip} "
# done
# ips="pip1 pip2 pip3 pip4 pip5"
# az network nat gateway create -n nat -g ${RG} -l ${LOCATION} --public-ip-addresses ${ips}

NAT_GW_NAME=$CLUSTER-ng
az network public-ip create -g $RG -n $CLUSTER-ip --allocation-method Static --ip-tags 'FirstPartyUsage=/DelegatedNetworkControllerTest' --tier Regional --version IPv4 -l $LOCATION --sku standard
az network nat gateway create -g $RG -n $NAT_GW_NAME -l $LOCATION --public-ip-addresses $CLUSTER-ip

# create vnetsubnets for overlay
echo "create vnet subnets for overlay"
echo "create vnet"
vnetName="net"
vnetAddressSpaceCIDR="10.0.0.0/9"

az network vnet create -n ${vnetName} -g ${RG} --address-prefixes ${vnetAddressSpaceCIDR} -l ${LOCATION}
echo "create vnet subnet"
vnetSubnetNameNodes="nodes"
vnetSubnetNamePods="pods"
vnetSubnetNodesCIDR="10.0.0.0/16"
vnetSubnetPodsCIDR="10.1.0.0/16"
podCIDR="10.128.0.0/9"
natGatewayID=$(az network nat gateway list -g ${RG} | jq -r '.[].id')
az network vnet subnet create -n ${vnetSubnetNameNodes} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetNodesCIDR} --nat-gateway ${natGatewayID} -g ${RG}
az network vnet subnet create -n ${vnetSubnetNamePods} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetPodsCIDR} --nat-gateway $NAT_GW_NAME -g ${RG}

# az role assignment create --assignee d0fdeb79-ee9b-464c-ae0f-ba72d307208d --role "Network Contributor" --scope /subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$vnetName
for attempt in $(seq 1 5); do
    echo "Attempting to execute subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -v -X PUT http://localhost:8080/VirtualNetwork/%2Fsubscriptions%2F9b8218f9-902a-4d20-a65c-e98acec5362f%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$vnetName/stampcreatorservicename'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

# # create customer vnet
# custVnetName="custvnet"
# az network vnet create --resource-group $RG --name $custVnetName --location $LOCATION --address-prefix $vnetAddressSpaceCIDR
# custSubnetName="delgpod"
# az network vnet subnet create --resource-group $RG --vnet-name $custVnetName --name $custSubnetName --address-prefixes $vnetSubnetPodsCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
TESTRG=swiftv2-runners-$RUNNERLOCATION
custVnetName=swiftvnet-$RUNNERLOCATION
custSubnetName="scaledel"
custVnetSubnetPodsCIDR="172.26.0.0/16"
az network vnet subnet create --resource-group $TESTRG --vnet-name $custVnetName --name $custSubnetName --address-prefixes $custVnetSubnetPodsCIDR --delegations Microsoft.SubnetDelegator/msfttestclients
for attempt in $(seq 1 5); do
    echo "Attempting to execute subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F9b8218f9-902a-4d20-a65c-e98acec5362f%2FresourceGroups%2F$TESTRG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$custVnetName%2Fsubnets%2F$custSubnetName'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

# script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -X PUT http://localhost:8080/DelegatedSubnet/%2Fsubscriptions%2F9b8218f9-902a-4d20-a65c-e98acec5362f%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$custVnetName%2Fsubnets%2F$custSubnetName'" /dev/null
# create cluster
echo "create cluster"
vnetID=$(az network vnet list -g ${RG} | jq -r '.[].id')
nodeSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNameNodes}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNamePods}']" | jq -r '.[].id')
az rest --method get --url /subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/$TESTRG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/$custSubnetName?api-version=2024-05-01
az aks create -n ${CLUSTER} -g ${RG} \
        -s Standard_D8_v3 -c 5 \
        --os-sku Ubuntu \
        -l ${LOCATION} \
        --service-cidr 192.168.0.0/16 --dns-service-ip 192.168.0.10 \
        --network-plugin azure \
        --tier standard \
        --kubernetes-version ${K8S_VER} \
        --vnet-subnet-id ${nodeSubnetID} \
        --pod-subnet-id ${podSubnetID} \
        --nodepool-tags fastpathenabled=true aks-nic-enable-multi-tenancy=true \
        --vm-set-type VirtualMachineScaleSets \
        --tags run_id=${RG} role=slo \
        --load-balancer-backend-pool-type nodeIP \
        --outbound-type userAssignedNATGateway \
        --no-ssh-key \
        --node-resource-group MC_sv2perf-$RG-$CLUSTER \
        --enable-managed-identity \
        --generate-ssh-keys \
        --yes
        
SV2_CLUSTER_RESOURCE_ID=$(az group show -n MC_sv2perf-$RG-$CLUSTER -o tsv --query id)
az tag update --resource-id $SV2_CLUSTER_RESOURCE_ID --operation Merge --tags SkipAutoDeleteTill=2032-12-31 skipGC="swift v2 perf" gc_skip="true"

for i in $(seq 1 ${NODEPOOLS}); do
    for attempt in $(seq 1 5); do
        echo "creating usernodepools: $attempt/15"
        az aks nodepool add --cluster-name ${CLUSTER} --name "userpool${i}" --resource-group ${RG} -s Standard_D4_v3 --os-sku Ubuntu --labels slo=true testscenario=swiftv2 --node-taints "slo=true:NoSchedule" --vnet-subnet-id ${nodeSubnetID} --pod-subnet-id ${podSubnetID} --tags fastpathenabled=true aks-nic-enable-multi-tenancy=true && break || echo "usernodepool creation attemped failed"
        sleep 60
    done
done 

for i in $(seq 1 ${NODEPOOLS}); do
    az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool${i}"
done
# scale nodepools
# for i in $(seq 1 ${NODEPOOLS}); do
#         az aks nodepool scale --cluster-name ${CLUSTER} --name "userpool${i}" --resource-group ${RG} -c ${NODEPOOL_SIZE}
#         sleep 300
# done

# uncomment if using for 'cluster churn' scenario
# for i in $(seq 1 ${NODEPOOLS}); do
#         az aks nodepool update --cluster-name ${CLUSTER} --name "userpool${i}" --resource-group ${RG} --enable-cluster-autoscaler --min-count 0 --max-count 500
# done

# # add prometheus nodepool
# export vnetGuid=$(az network vnet show --name $custVnetName --resource-group $RG --query resourceGuid --output tsv)
# export subnetResourceId=$(az network vnet subnet show --name $custSubnetName --vnet-name $custVnetName --resource-group $RG --query id --output tsv)
# export subnetGUID=$(az rest --method get --url "/subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/delgpod?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

export vnetGuid=$(az network vnet show --name $custVnetName --resource-group $TESTRG --query resourceGuid --output tsv)
export subnetResourceId=$(az network vnet subnet show --name $custSubnetName --vnet-name $custVnetName --resource-group $TESTRG --query id --output tsv)
export subnetGUID=$(az rest --method get --url "/subscriptions/9b8218f9-902a-4d20-a65c-e98acec5362f/resourceGroups/$TESTRG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/$custSubnetName?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

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
    az aks nodepool add --cluster-name ${CLUSTER} --name promnodepool --resource-group ${RG} -c 1 -s Standard_D64_v3 --os-sku Ubuntu --labels prometheus=true --vnet-subnet-id ${nodeSubnetID} --pod-subnet-id ${podSubnetID} && break || echo "usernodepool creation attemped failed"
    sleep 60
done

az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name promnodepool

az aks get-credentials -n ${CLUSTER} -g ${RG} --admin

envsubst < swiftv2kubeobjects/pn.yaml | kubectl apply -f -

sleep 60

if kubectl get pn pn100 -o yaml | grep 'status: Ready' > /dev/null; then
    echo "PN is ready"
else
    exit 1
fi
