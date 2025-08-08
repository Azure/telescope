# #!/bin/bash

set -ex

RG=$RUN_ID 
CLUSTER="large"
SUBSCRIPTION="9b8218f9-902a-4d20-a65c-e98acec5362f"
K8S_VER=1.30
NODEPOOLS=1

# Source shared configuration if available
if [[ -f "$(dirname "$0")/shared-config.sh" ]]; then
    echo "Loading shared configuration..."
    source "$(dirname "$0")/shared-config.sh"
else
    # Fallback to direct configuration (should match runCustomerSetup.sh values)
    CUST_VNET_NAME=custvnet
    CUST_SCALE_DEL_SUBNET="scaledel"
    CUST_SUB=${SUBSCRIPTION:-9b8218f9-902a-4d20-a65c-e98acec5362f}
    CUST_RG="sv2-perf-cust-${LOCATION:-uksouth}"
    ACR_NAME="sv2perfacr$LOCATION"
    SHARED_KUBELET_IDENTITY_NAME="sharedKubeletIdentity"
    SHARED_CONTROL_PLANE_IDENTITY_NAME="sharedControlPlaneIdentity"
fi

# Get target user node count from environment variable (used only for buffer pool calculation)
TARGET_USER_NODE_COUNT=$NODES_PER_NODEPOOL
echo "Target user nodepool size for buffer calculation: $TARGET_USER_NODE_COUNT nodes"

# Function to create and verify nodepool
create_and_verify_nodepool() {
    local cluster_name=$1
    local nodepool_name=$2
    local resource_group=$3
    local node_count=${4:-1}
    local node_size=${5:-"Standard_D4_v3"}
    local node_subnet_id=$6
    local pod_subnet_id=$7
    local labels=${8:-""}
    local taints=${9:-""}
    local extra_args=${10:-""}
    
    echo "Creating nodepool: $nodepool_name with $node_count nodes of size $node_size"
    
    # Build the nodepool creation command
    local nodepool_cmd="az aks nodepool add --cluster-name ${cluster_name} --name ${nodepool_name} --resource-group ${resource_group}"
    nodepool_cmd+=" --node-count ${node_count} -s ${node_size} --os-sku Ubuntu"
    nodepool_cmd+=" --vnet-subnet-id ${node_subnet_id} --pod-subnet-id ${pod_subnet_id}"
    nodepool_cmd+=" --tags fastpathenabled=true aks-nic-enable-multi-tenancy=true"
    
    # Add optional labels
    if [[ -n "$labels" ]]; then
        nodepool_cmd+=" --labels ${labels}"
    fi
    
    # Add optional taints
    if [[ -n "$taints" ]]; then
        nodepool_cmd+=" --node-taints \"${taints}\""
    fi
    
    # Add any extra arguments
    if [[ -n "$extra_args" ]]; then
        nodepool_cmd+=" ${extra_args}"
    fi
    
    # Create nodepool with retry logic
    local max_attempts=5
    for attempt in $(seq 1 $max_attempts); do
        echo "Creating nodepool ${nodepool_name}: attempt $attempt/$max_attempts"
        if eval $nodepool_cmd; then
            echo "Nodepool ${nodepool_name} creation command succeeded"
            break
        else
            echo "Nodepool ${nodepool_name} creation attempt $attempt failed"
            if [[ $attempt -eq $max_attempts ]]; then
                echo "ERROR: Failed to create nodepool ${nodepool_name} after $max_attempts attempts"
                return 1
            fi
            sleep 15
        fi
    done
    
    # Wait for nodepool to be ready with retry logic and timeout
    echo "Waiting for nodepool ${nodepool_name} to be ready..."
    local timeout=900  # 15 minutes timeout for nodepool
    local retry_interval=30  # Check every 30 seconds
    local elapsed=0
    
    while [ $elapsed -lt $timeout ]; do
        local status=$(az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --query "provisioningState" --output tsv 2>/dev/null || echo "QueryFailed")
        local power_state=$(az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --query "powerState.code" --output tsv 2>/dev/null || echo "QueryFailed")
        
        echo "Nodepool ${nodepool_name} status: $status, Power state: $power_state (elapsed: ${elapsed}s)"
        
        case $status in
            "Succeeded")
                if [[ $power_state == "Running" ]]; then
                    echo "Nodepool ${nodepool_name} is ready and running"
                    return 0
                else
                    echo "Nodepool succeeded but not in Running power state, waiting..."
                fi
                ;;
            "Creating"|"Scaling"|"Upgrading")
                echo "Nodepool ${nodepool_name} is still provisioning, waiting..."
                ;;
            "Failed"|"Canceled"|"Deleting"|"Deleted")
                echo "Nodepool ${nodepool_name} is in failed state: $status. Exiting."
                az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --output table
                return 1
                ;;
            "QueryFailed"|"")
                echo "Failed to query nodepool status. This might be temporary, continuing to wait..."
                ;;
            *)
                echo "Unknown nodepool status: $status. Continuing to wait..."
                ;;
        esac
        
        sleep $retry_interval
        elapsed=$((elapsed + retry_interval))
    done
    
    echo "Timeout reached waiting for nodepool ${nodepool_name} to be ready. Final status: $status"
    echo "ERROR: Nodepool ${nodepool_name} failed to reach ready state within timeout."
    az aks nodepool show --resource-group ${resource_group} --cluster-name ${cluster_name} --name ${nodepool_name} --output table
    return 1
}

# Function to create AKS cluster
create_aks_cluster() {
    local cluster_name=$1
    local resource_group=$2
    local location=$3
    local k8s_version=$4
    local node_subnet_id=$5
    local pod_subnet_id=$6
    
    echo "Creating AKS cluster: $cluster_name in resource group: $resource_group"
    
    # Get the kubelet identity ID from the shared infrastructure resource group
    local kubelet_identity_id=$(az identity show --name $SHARED_KUBELET_IDENTITY_NAME --resource-group ${CUST_RG:-$custRG} --query id -o tsv)
    
    if [ -z "$kubelet_identity_id" ]; then
        echo "ERROR: Failed to get kubelet identity ID from resource group ${CUST_RG:-$custRG}"
        exit 1
    fi
    
    echo "Using kubelet identity: $kubelet_identity_id"

    local control_plane_identity_id=$(az identity show --name $SHARED_CONTROL_PLANE_IDENTITY_NAME --resource-group ${CUST_RG:-$custRG} --query id -o tsv)

    if [ -z "$control_plane_identity_id" ]; then
        echo "ERROR: Failed to get control plane identity ID from resource group ${CUST_RG:-$custRG}"
        exit 1
    fi

    echo "Using control plane identity: $control_plane_identity_id"

    # Create the AKS cluster with the specified parameters
    az aks create -n ${cluster_name} -g ${resource_group} \
        -s Standard_D4_v3 -c 5 \
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
        --assign-kubelet-identity ${kubelet_identity_id} \
        --assign-identity ${control_plane_identity_id} \
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
az network vnet subnet create -n ${vnetSubnetNameNodes} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetNodesCIDR} --nat-gateway ${natGatewayID} --default-outbound-access false -g ${RG}
az network vnet subnet create -n ${vnetSubnetNamePods} --vnet-name ${vnetName} --address-prefixes ${vnetSubnetPodsCIDR} --nat-gateway $NAT_GW_NAME --default-outbound-access false -g ${RG}

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

# Create user nodepool with 1 node (will be scaled later by scale-cluster.sh)
INITIAL_USER_NODES=1  # Always start with 1 node, regardless of target
echo "Creating user nodepool with $INITIAL_USER_NODES node (will be scaled to $TARGET_USER_NODE_COUNT later)..."
if ! create_and_verify_nodepool "${CLUSTER}" "userpool1" "${RG}" "$INITIAL_USER_NODES" "Standard_D4_v3" "${nodeSubnetID}" "${podSubnetID}" "slo=true testscenario=swiftv2 agentpool=userpool1" "slo=true:NoSchedule"; then
    echo "ERROR: Failed to create user nodepool"
    exit 1
fi

# Calculate buffer pool size based on target user nodepool size (not initial size)
BUFFER_NODE_COUNT=$(( (TARGET_USER_NODE_COUNT * 5 + 50) / 100 ))  # 5% of target, rounded up
if [[ $BUFFER_NODE_COUNT -lt 1 ]]; then
    BUFFER_NODE_COUNT=1
fi

echo "Creating buffer nodepool with $BUFFER_NODE_COUNT nodes (5% of target $TARGET_USER_NODE_COUNT user nodes)..."
if ! create_and_verify_nodepool "${CLUSTER}" "bufferpool1" "${RG}" "$BUFFER_NODE_COUNT" "Standard_D4_v3" "${nodeSubnetID}" "${podSubnetID}" "role=buffer testscenario=swiftv2 agentpool=bufferpool1" "" ""; then
    echo "ERROR: Failed to create buffer nodepool"
    exit 1
fi

# customer vnet (created using runCustomerSetup.sh manually)

export custVnetGUID=$(az network vnet show --name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query resourceGuid --output tsv)
export custSubnetResourceId=$(az network vnet subnet show --name ${CUST_SCALE_DEL_SUBNET} --vnet-name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query id --output tsv)
export custSubnetGUID=$(az rest --method get --url "/subscriptions/${CUST_SUB}/resourceGroups/${CUST_RG}/providers/Microsoft.Network/virtualNetworks/${CUST_VNET_NAME}/subnets/${CUST_SCALE_DEL_SUBNET}?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

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
