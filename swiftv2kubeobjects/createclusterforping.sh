# #!/bin/bash

set -ex

RG=$RUN_ID 
CLUSTER="large"
SUBSCRIPTION="9b8218f9-902a-4d20-a65c-e98acec5362f"
K8S_VER=1.30
NODEPOOLS=1

# Function to create AKS cluster
create_aks_cluster() {
    local cluster_name=$1
    local resource_group=$2
    local location=$3
    local k8s_version=$4
    local node_subnet_id=$5
    local pod_subnet_id=$6
    
    echo "Creating AKS cluster: $cluster_name in resource group: $resource_group"
    az aks create -n ${cluster_name} -g ${resource_group} \
        -s Standard_D8_v3 -c 5 \
        --os-sku Ubuntu \
        -l ${location} \
        --service-cidr 192.168.0.0/16 --dns-service-ip 192.168.0.10 \
        --network-plugin azure \
        --tier standard \
        --kubernetes-version ${k8s_version} \
        --vnet-subnet-id ${node_subnet_id} \
        --pod-subnet-id ${pod_subnet_id} \
        --nodepool-tags fastpathenabled=true aks-nic-enable-multi-tenancy=true \
        --vm-set-type VirtualMachineScaleSets \
        --tags run_id=${resource_group} role=slo \
        --load-balancer-backend-pool-type nodeIP \
        --outbound-type userAssignedNATGateway \
        --no-ssh-key \
        --node-resource-group MC_sv2perf-$resource_group-$cluster_name \
        --enable-managed-identity \
        --generate-ssh-keys \
        --yes
} 

#az login
# create RG
echo "Create RG"
date=$(date -d "+1 week" +"%Y-%m-%d")
az group create --location $LOCATION --name $RG --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

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

# az role assignment create --assignee d0fdeb79-ee9b-464c-ae0f-ba72d307208d --role "Network Contributor" --scope /subscriptions/${SUBSCRIPTION}/resourceGroups/$RG/providers/Microsoft.Network/virtualNetworks/$vnetName
for attempt in $(seq 1 5); do
    echo "Attempting to set stampcreatorservicename using subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -v -X PUT http://localhost:8080/VirtualNetwork/%2Fsubscriptions%2F${SUBSCRIPTION}%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$vnetName/stampcreatorservicename'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

# create cluster
echo "create cluster"
vnetID=$(az network vnet list -g ${RG} | jq -r '.[].id')
nodeSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNameNodes}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNamePods}']" | jq -r '.[].id')

# Call the function to create the cluster
create_aks_cluster "${CLUSTER}" "${RG}" "${LOCATION}" "${K8S_VER}" "${nodeSubnetID}" "${podSubnetID}"

# Wait for cluster to be ready with retry logic and timeout
echo "Waiting for cluster to be ready..."
TIMEOUT=1800  # 30 minutes timeout
RETRY_INTERVAL=30  # Check every 30 seconds
elapsed=0

while [ $elapsed -lt $TIMEOUT ]; do
    STATUS=$(az aks show --name $CLUSTER --resource-group $RG --query "provisioningState" --output tsv 2>/dev/null || echo "QueryFailed")
    echo "Current cluster status: $STATUS (elapsed: ${elapsed}s)"
    
    case $STATUS in
        "Succeeded")
            echo "Cluster is ready"
            break
            ;;
        "Creating"|"Updating"|"Upgrading")
            echo "Cluster is still provisioning, waiting..."
            ;;
        "Canceled")
            echo "Cluster creation was canceled. Attempting to restart creation..."
            # Attempt to recreate the cluster using the function
            create_aks_cluster "${CLUSTER}" "${RG}" "${LOCATION}" "${K8S_VER}" "${nodeSubnetID}" "${podSubnetID}"
            echo "Cluster recreation initiated, continuing to wait..."
            ;;
        "Failed"|"Deleting"|"Deleted")
            echo "Cluster is in failed state: $STATUS. Exiting."
            exit 1
            ;;
        "QueryFailed"|"")
            echo "Failed to query cluster status. This might be temporary, continuing to wait..."
            ;;
        *)
            echo "Unknown cluster status: $STATUS. Continuing to wait..."
            ;;
    esac
    
    if [[ $STATUS == "Succeeded" ]]; then
        break
    fi
    
    sleep $RETRY_INTERVAL
    elapsed=$((elapsed + RETRY_INTERVAL))
done

if [ $elapsed -ge $TIMEOUT ]; then
    echo "Timeout reached waiting for cluster to be ready. Final status: $STATUS"
    exit 1
fi
        
SV2_CLUSTER_RESOURCE_ID=$(az group show -n MC_sv2perf-$RG-$CLUSTER -o tsv --query id)
date=$(date -d "+1 week" +"%Y-%m-%d")
az tag update --resource-id $SV2_CLUSTER_RESOURCE_ID --operation Merge --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true"

for attempt in $(seq 1 5); do
    echo "creating usernodepool: $attempt/5"
    az aks nodepool add --cluster-name ${CLUSTER} --name "userpool1" --resource-group ${RG} -s Standard_D4_v3 --os-sku Ubuntu --labels slo=true testscenario=swiftv2 --node-taints "slo=true:NoSchedule" --vnet-subnet-id ${nodeSubnetID} --pod-subnet-id ${podSubnetID} --tags fastpathenabled=true aks-nic-enable-multi-tenancy=true && break || echo "usernodepool creation attemped failed"
    sleep 15
done

# Wait for user nodepool to be ready with retry logic and timeout
echo "Waiting for user nodepool to be ready..."
NODEPOOL_TIMEOUT=900  # 15 minutes timeout for nodepool
NODEPOOL_RETRY_INTERVAL=30  # Check every 30 seconds
nodepool_elapsed=0

while [ $nodepool_elapsed -lt $NODEPOOL_TIMEOUT ]; do
    NODEPOOL_STATUS=$(az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool1" --query "provisioningState" --output tsv 2>/dev/null || echo "QueryFailed")
    NODEPOOL_POWER_STATE=$(az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool1" --query "powerState.code" --output tsv 2>/dev/null || echo "QueryFailed")
    
    echo "Current nodepool status: $NODEPOOL_STATUS, Power state: $NODEPOOL_POWER_STATE (elapsed: ${nodepool_elapsed}s)"
    
    case $NODEPOOL_STATUS in
        "Succeeded")
            if [[ $NODEPOOL_POWER_STATE == "Running" ]]; then
                echo "User nodepool is ready and running"
                break
            else
                echo "Nodepool succeeded but not in Running power state, waiting..."
            fi
            ;;
        "Creating"|"Scaling"|"Upgrading")
            echo "User nodepool is still provisioning, waiting..."
            ;;
        "Failed"|"Canceled"|"Deleting"|"Deleted")
            echo "User nodepool is in failed state: $NODEPOOL_STATUS. Exiting."
            # Show nodepool details for debugging
            az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool1" --output table
            exit 1
            ;;
        "QueryFailed"|"")
            echo "Failed to query nodepool status. This might be temporary, continuing to wait..."
            ;;
        *)
            echo "Unknown nodepool status: $NODEPOOL_STATUS. Continuing to wait..."
            ;;
    esac
    
    sleep $NODEPOOL_RETRY_INTERVAL
    nodepool_elapsed=$((nodepool_elapsed + NODEPOOL_RETRY_INTERVAL))
done

if [ $nodepool_elapsed -ge $NODEPOOL_TIMEOUT ]; then
    echo "Timeout reached waiting for user nodepool to be ready. Final status: $NODEPOOL_STATUS"
    echo "ERROR: Nodepool failed to reach ready state within timeout."
    az aks nodepool show --resource-group ${RG} --cluster-name ${CLUSTER} --name "userpool1" --output table
    exit 1
fi

# customer vnet (created using runCustomerSetup.sh manually)
custVnetName=custvnet
custScaleDelSubnet="scaledel"
custSub=9b8218f9-902a-4d20-a65c-e98acec5362f
custRG="sv2-perf-infra-customer"

export custVnetGUID=$(az network vnet show --name $custVnetName --resource-group $custRG --query resourceGuid --output tsv)
export custSubnetResourceId=$(az network vnet subnet show --name $custScaleDelSubnet --vnet-name $custVnetName --resource-group $custRG --query id --output tsv)
export custSubnetGUID=$(az rest --method get --url "/subscriptions/${custSub}/resourceGroups/$custRG/providers/Microsoft.Network/virtualNetworks/$custVnetName/subnets/$custScaleDelSubnet?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

az aks get-credentials -n ${CLUSTER} -g ${RG} --admin

envsubst < swiftv2kubeobjects/pn.yaml | kubectl apply -f -

# Wait for PN to be ready with retry logic
echo "Waiting for PN (Private Network) to be ready..."
PN_TIMEOUT=300  # 5 minutes timeout for PN
PN_RETRY_INTERVAL=15  # Check every 15 seconds
pn_elapsed=0

while [ $pn_elapsed -lt $PN_TIMEOUT ]; do
    if kubectl get pn pn100 -o yaml 2>/dev/null | grep 'status: Ready' > /dev/null; then
        echo "PN is ready"
        break
    else
        echo "PN not ready yet, waiting... (elapsed: ${pn_elapsed}s)"
        sleep $PN_RETRY_INTERVAL
        pn_elapsed=$((pn_elapsed + PN_RETRY_INTERVAL))
    fi
done

if [ $pn_elapsed -ge $PN_TIMEOUT ]; then
    echo "Timeout reached waiting for PN to be ready"
    kubectl get pn pn100 -o yaml 2>/dev/null || echo "Failed to get PN status"
    exit 1
fi

echo "Script completed successfully!"
