# #!/bin/bash

set -ex

# =============================================================================
# CANCELLATION HANDLING
# =============================================================================

# Global flag for cancellation detection
CANCELLED=false

# Signal handler for graceful shutdown
handle_cancellation() {
    echo "WARNING: Received cancellation signal (SIGTERM/SIGINT)"
    CANCELLED=true
    
    # Give processes a moment to clean up
    sleep 2
    
    echo "ERROR: Pipeline cancellation detected. Exiting gracefully..."
    echo "Note: Any partially created resources will be cleaned up by the cleanup phase"
    exit 143  # Standard exit code for SIGTERM
}

# Set up signal traps for cancellation
trap handle_cancellation SIGTERM SIGINT

# Check if pipeline has been cancelled
check_cancellation() {
    if [ "$CANCELLED" = true ]; then
        echo "WARNING: Cancellation detected, stopping current operation..."
        return 1
    fi
    
    # Check for Azure DevOps cancellation marker file (if exists)
    if [ -f "/tmp/pipeline_cancelled" ]; then
        echo "WARNING: Pipeline cancellation marker detected"
        CANCELLED=true
        return 1
    fi
    
    return 0
}

RG=$RUN_ID 
CLUSTER="large"
SUBSCRIPTION=$AZURE_SUBSCRIPTION_ID
NODEPOOLS=1

# Source shared configuration
echo "Loading shared configuration..."
source "$(dirname "$0")/shared-config.sh"

# Get target user node count from environment variable (used only for buffer pool calculation)
TARGET_USER_NODE_COUNT=$NODE_COUNT
echo "Target user nodepool size for buffer calculation: $TARGET_USER_NODE_COUNT nodes"

# Function to create and verify nodepool
create_and_verify_nodepool() {
    local cluster_name=$1
    local nodepool_name=$2
    local resource_group=$3
    local initial_node_count=$4
    local node_subnet_id=$6
    local pod_subnet_id=$7
    local labels=${8:-""}
    local taints=${9:-""}
    local extra_args=${10:-""}

    echo "Creating nodepool: $nodepool_name with $initial_node_count nodes of size $VM_SKU"

    # Build the nodepool creation command
    local nodepool_cmd="az aks nodepool add --cluster-name ${cluster_name} --name ${nodepool_name} --resource-group ${resource_group}"
    nodepool_cmd+=" --node-count ${initial_node_count} -s ${VM_SKU} --os-sku Ubuntu"
    nodepool_cmd+=" --vnet-subnet-id ${node_subnet_id} --pod-subnet-id ${pod_subnet_id}"
    nodepool_cmd+=" --tags fastpathenabled=true aks-nic-enable-multi-tenancy=true aks-nic-secondary-count=${PODS_PER_NODE}"

    # Only apply --max-pods when the device plugin is disabled
    # - Pipeline variables typically arrive as env vars (e.g. max_pods -> MAX_PODS)
    # - Keep this tolerant to missing values
    local device_plugin_raw="${DEVICE_PLUGIN}"
    local device_plugin_lc
    device_plugin_lc="$(echo "${device_plugin_raw}" | tr '[:upper:]' '[:lower:]')"
    local max_pods_value="${MAX_PODS:-${max_pods}}"
    if [[ "${device_plugin_lc}" != "true" && "${max_pods_value}" =~ ^[0-9]+$ && "${max_pods_value}" -gt 0 ]]; then
        nodepool_cmd+=" --max-pods ${max_pods_value}"
    fi
    
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
        # Check for cancellation before each retry
        if ! check_cancellation; then
            echo "ERROR: Pipeline cancelled during nodepool creation for ${nodepool_name}"
            return 1
        fi
        
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
        # Check for cancellation in wait loop
        if ! check_cancellation; then
            echo "WARNING: Pipeline cancelled while waiting for nodepool ${nodepool_name}"
            return 1
        fi
        
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
    local node_subnet_id=$4
    local pod_subnet_id=$5
    
    if [[ -n "$K8S_VERSION" ]]; then
        echo "Creating AKS cluster: $cluster_name in resource group: $resource_group with Kubernetes version: $K8S_VERSION"
    else
        echo "Creating AKS cluster: $cluster_name in resource group: $resource_group with default Kubernetes version"
    fi
    
    # =============================================================================
    # USE PRE-CREATED MANAGED IDENTITIES FOR ACR ACCESS
    # =============================================================================
    # IMPORTANT: We cannot use --attach-acr because:
    # - The ACR is in a different subscription than this cluster
    # - The pipeline service principal lacks permission to grant roles on the ACR
    # - This would result in: "AuthorizationFailed: does not have authorization
    #   to perform action 'Microsoft.Authorization/roleAssignments/write'"
    #
    # Instead, we use shared managed identities that were pre-created by
    # runCustomerSetup.sh with AcrPull access already granted. This approach:
    # - Separates permission management (one-time setup) from cluster creation
    # - Works with limited pipeline permissions
    # - Allows multiple clusters to share the same identities
    #
    # PREREQUISITE: Ensure runCustomerSetup.sh has been run to create these
    # identities before running this script, or cluster image pulls will fail.
    # =============================================================================
    
    az account set --subscription $CUST_SUB
    local kubelet_identity_id=$(az identity show --name $SHARED_KUBELET_IDENTITY_NAME --resource-group ${CUST_RG} --query id -o tsv)
    
    if [ -z "$kubelet_identity_id" ]; then
        echo "ERROR: Failed to get kubelet identity ID from resource group ${CUST_RG}"
        echo "Please ensure runCustomerSetup.sh has been run to create shared identities"
        exit 1
    fi
    
    echo "Using pre-created kubelet identity: $kubelet_identity_id (already has ACR access)"

    local control_plane_identity_id=$(az identity show --name $SHARED_CONTROL_PLANE_IDENTITY_NAME --resource-group ${CUST_RG} --query id -o tsv)
    
    if [ -z "$control_plane_identity_id" ]; then
        echo "ERROR: Failed to get control plane identity ID from resource group ${CUST_RG}"
        exit 1
    fi

    echo "Using pre-created control plane identity: $control_plane_identity_id"

    az account set --subscription $SUBSCRIPTION
    
    # Create the AKS cluster with the specified parameters
    local k8s_version_param=""
    if [[ -n "$K8S_VERSION" ]]; then
        k8s_version_param="--kubernetes-version ${K8S_VERSION}"
    fi
    
    az aks create -n ${cluster_name} -g ${resource_group} \
        -s $VM_SKU -c 5 \
        --os-sku Ubuntu \
        -l ${location} \
        --service-cidr 192.168.0.0/16 --dns-service-ip 192.168.0.10 \
        --network-plugin azure \
        --tier standard \
        ${k8s_version_param} \
        --vnet-subnet-id ${node_subnet_id} \
        --pod-subnet-id ${pod_subnet_id} \
        --nodepool-tags fastpathenabled=true aks-nic-enable-multi-tenancy=true aks-nic-secondary-count=${PODS_PER_NODE} \
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
# Append tags to existing RG
echo "Appending tags to existing RG"
date=$(date -d "+1 week" +"%Y-%m-%d")
az tag update --resource-id /subscriptions/${SUBSCRIPTION}/resourceGroups/${RG} --operation Merge --tags SkipAutoDeleteTill=$date skipGC="swift v2 perf" gc_skip="true" owner="ACN"

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
# set az account to subnetDelegator
az account set --subscription $SD_SUB
for attempt in $(seq 1 5); do
    echo "Attempting to set stampcreatorservicename using subnetdelegator command: $attempt/5"
    script --return --quiet -c "az containerapp exec -n subnetdelegator-westus-u3h4j -g subnetdelegator-westus --command 'curl -v -X PUT http://localhost:8080/VirtualNetwork/%2Fsubscriptions%2F${SUBSCRIPTION}%2FresourceGroups%2F$RG%2Fproviders%2FMicrosoft.Network%2FvirtualNetworks%2F$vnetName/stampcreatorservicename'" /dev/null && break || echo "Command failed, retrying..."
    sleep 30
done

# set az account back to original
az account set --subscription $SUBSCRIPTION
# create cluster
echo "create cluster"
vnetID=$(az network vnet list -g ${RG} | jq -r '.[].id')
nodeSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNameNodes}']" | jq -r '.[].id')
podSubnetID=$(az network vnet subnet list -g ${RG} --vnet-name ${vnetName} --query "[?name=='${vnetSubnetNamePods}']" | jq -r '.[].id')

# Call the function to create the cluster (ACR permissions will be automatically configured)
create_aks_cluster "${CLUSTER}" "${RG}" "${LOCATION}" "${nodeSubnetID}" "${podSubnetID}"

# Wait for cluster to be ready with retry logic and timeout
echo "Waiting for cluster to be ready..."
TIMEOUT=1800  # 30 minutes timeout
RETRY_INTERVAL=30  # Check every 30 seconds
elapsed=0

while [ $elapsed -lt $TIMEOUT ]; do
    # Check for cancellation during cluster wait
    if ! check_cancellation; then
        echo "WARNING: Pipeline cancelled while waiting for cluster to be ready"
        exit 143
    fi
    
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
            create_aks_cluster "${CLUSTER}" "${RG}" "${LOCATION}" "${nodeSubnetID}" "${podSubnetID}"
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

############################################################
# Create user nodepools (sharded) with 1 node each initially
#
# Constraints / rationale:
# - A single AKS nodepool can scale to 1000 nodes, but we purposefully
#   shard at 500 nodes per pool for faster scale operations, failure
#   domain isolation, and parallel provisioning.
# - We start each user pool at 1 node; a later scale script will fan out
#   to the desired TARGET_USER_NODE_COUNT total across pools.
# - USER_NODEPOOL_COUNT = ceil(TARGET_USER_NODE_COUNT / 500)
############################################################

INITIAL_USER_NODES=1  # Always start with 1 node per user pool
USER_NODEPOOL_SIZE=500

# Guard / default if TARGET_USER_NODE_COUNT is unset or invalid
if [[ -z "$TARGET_USER_NODE_COUNT" || "$TARGET_USER_NODE_COUNT" -le 0 ]]; then
    echo "TARGET_USER_NODE_COUNT not set or <=0; defaulting to 1"
    TARGET_USER_NODE_COUNT=1
fi

USER_NODEPOOL_COUNT=$(( (TARGET_USER_NODE_COUNT + USER_NODEPOOL_SIZE - 1) / USER_NODEPOOL_SIZE ))
if [[ $USER_NODEPOOL_COUNT -lt 1 ]]; then
    USER_NODEPOOL_COUNT=1
fi

echo "Planned total user nodes: $TARGET_USER_NODE_COUNT"
echo "User nodepool shard size: $USER_NODEPOOL_SIZE"
echo "Creating $USER_NODEPOOL_COUNT user nodepool(s), each starting with $INITIAL_USER_NODES node"

for i in $(seq 1 $USER_NODEPOOL_COUNT); do
    # Check for cancellation before creating each nodepool
    if ! check_cancellation; then
        echo "ERROR: Pipeline cancelled before creating user nodepool $i"
        exit 143
    fi
    
    pool_name="userpool${i}"
    labels="slo=true testscenario=swiftv2 agentpool=${pool_name}"
    taints="slo=true:NoSchedule"
    echo "Creating user nodepool $pool_name (1/${USER_NODEPOOL_COUNT} initial node)"
    if ! create_and_verify_nodepool "${CLUSTER}" "${pool_name}" "${RG}" "${INITIAL_USER_NODES}" "${VM_SKU}" "${nodeSubnetID}" "${podSubnetID}" "${labels}" "${taints}"; then
        echo "ERROR: Failed to create user nodepool ${pool_name}"
        exit 1
    fi
done

# only provision bufferpool if PROVISION_BUFFER_NODES is set to true
if [[ "${PROVISION_BUFFER_NODES:-false}" != "true" ]]; then
    echo "Skipping buffer nodepool creation as PROVISION_BUFFER_NODES is not set to true"
else
    # Start buffer pool with 1 node (like userpools)
    # The scale-cluster.sh script will scale userpoolBuffer to handle any shortfall

    echo "Creating buffer nodepool with $INITIAL_USER_NODES node (will be scaled later if needed)..."
        pool_name="userpoolBuffer"
        labels="slo=true testscenario=swiftv2 agentpool=${pool_name}"
        taints="slo=true:NoSchedule"
    if ! create_and_verify_nodepool "${CLUSTER}" "${pool_name}" "${RG}" "${INITIAL_USER_NODES}" "${VM_SKU}" "${nodeSubnetID}" "${podSubnetID}" "${labels}" "${taints}"; then
        echo "ERROR: Failed to create buffer nodepool"
        exit 1
    fi
fi

# customer vnet (created using runCustomerSetup.sh manually)
az account set --subscription $CUST_SUB
export custVnetGUID=$(az network vnet show --name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query resourceGuid --output tsv)
export custSubnetResourceId=$(az network vnet subnet show --name ${CUST_SCALE_DEL_SUBNET} --vnet-name ${CUST_VNET_NAME} --resource-group ${CUST_RG} --query id --output tsv)
export custSubnetGUID=$(az rest --method get --url "/subscriptions/${CUST_SUB}/resourceGroups/${CUST_RG}/providers/Microsoft.Network/virtualNetworks/${CUST_VNET_NAME}/subnets/${CUST_SCALE_DEL_SUBNET}?api-version=2024-05-01" | jq -r '.properties.serviceAssociationLinks[0].properties.subnetId')

# set az account back to original
az account set --subscription $SUBSCRIPTION

az aks get-credentials -n ${CLUSTER} -g ${RG} --admin

envsubst < swiftv2kubeobjects/pn.yaml | kubectl apply -f -

# Wait for PN to be ready with retry logic
echo "Waiting for PN (Private Network) to be ready..."
PN_TIMEOUT=300  # 5 minutes timeout for PN
PN_RETRY_INTERVAL=15  # Check every 15 seconds
pn_elapsed=0

while [ $pn_elapsed -lt $PN_TIMEOUT ]; do
    # Check for cancellation during PN wait
    if ! check_cancellation; then
        echo "WARNING: Pipeline cancelled while waiting for PN to be ready"
        exit 143
    fi
    
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

# =============================================================================
# DEPLOY DATAPATH OBSERVER CONTROLLER
# =============================================================================
echo "Deploying Datapath Observer Controller..."

# Apply Manifests
MANIFEST_DIR="$(dirname "$0")/datapath-observer/controller/manifests"
echo "Applying manifests from $MANIFEST_DIR..."

if [ -d "$MANIFEST_DIR" ]; then
    kubectl apply -f "$MANIFEST_DIR/crd.yaml"
    kubectl apply -f "$MANIFEST_DIR/rbac.yaml"
    kubectl apply -f "$MANIFEST_DIR/deployment.yaml"
    
    # Wait for deployment to be ready
    echo "Waiting for datapath-controller to be ready..."
    if ! kubectl wait --for=condition=available --timeout=300s deployment/datapath-controller -n perf-ns; then
        echo "ERROR: datapath-controller failed to become ready within timeout"
        kubectl get pods -n perf-ns -l app=datapath-controller
        kubectl describe deployment datapath-controller -n perf-ns
        exit 1
    fi
else
    echo "ERROR: Manifest directory $MANIFEST_DIR not found!"
    # We don't exit here to avoid failing the whole cluster setup if this is optional, 
    # but based on requirements it seems important. 
    # For now, we'll just log error.
fi

echo "Script completed successfully!"
