import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common

SUBSCRIPTION_ID = "$(subscription_id)"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "$(location)"
CLUSTER_NAME = "$(cluster_name)"
SERVICE_CONNECTION = "$(AZURE_SERVICE_CONNECTION)"
K8S_VERSION = "1.33.0"

VNET_NAME = "${CLUSTER_NAME}-net"
IDENTITY_NAME = "${CLUSTER_NAME}-identity"
FW_NAME = "${CLUSTER_NAME}-firewall"
JUMPBOX_NAME = "${CLUSTER_NAME}-jumpbox"

# Small values for small scare e2e testing; replace with the lines below for full 15K run
# USER_TOTAL_NODES = 14997
# MAX_NODES_PER_POOL = 800
USER_TOTAL_NODES = 100
MAX_NODES_PER_POOL = 20

_userPools = [azure.NodePool {
    name = pool.name
    sku = pool.sku
    count = pool.count
    vnetSubnetId = "$(NODES_SUBNET_ID)"
    osSKU = "Ubuntu"
} for pool in azure.PlanNodePools({"$(user_pool_vm_size)": USER_TOTAL_NODES}, MAX_NODES_PER_POOL)]


createClusterScript = """
NETWORK_DATAPLANE="$(network_dataplane)"
NETWORK_DATAPLANE_FLAG=""
if [ -n "$NETWORK_DATAPLANE" ]; then
  NETWORK_DATAPLANE_FLAG="--network-dataplane $NETWORK_DATAPLANE"
fi

az extension add --name aks-preview --allow-preview true --upgrade --yes

az aks create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${CLUSTER_NAME}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "${K8S_VERSION}" \\
  --dns-name-prefix "${CLUSTER_NAME}-dns" \\
  --tier standard \\
  --assign-identity "$(IDENTITY_ID)" \\
  --tags SkipAKSCluster=true \\
  --control-plane-scaling-size H8 \\
  --nodepool-name system \\
  --node-count 3 \\
  --node-vm-size Standard_D48ds_v5 \\
  --max-pods 60 \\
  --os-sku Ubuntu \\
  --vnet-subnet-id "$(NODES_SUBNET_ID)" \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --outbound-type userDefinedRouting \\
  --enable-private-cluster \\
  --enable-apiserver-vnet-integration \\
  --apiserver-subnet-id "$(APISERVER_SUBNET_ID)" \\
  --generate-ssh-keys \\
  $NETWORK_DATAPLANE_FLAG
"""

output = ap.Pipeline {
    name = "15K Nodes Cluster Creation"

    trigger = "none"
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "subscription_id"
            displayName = "Subscription ID"
            type = "string"
            default = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
        }
        ap.Parameter {
            name = "location"
            displayName = "Azure region"
            type = "string"
            default = "eastasia"
        }
        ap.Parameter {
            name = "cluster_name"
            displayName = "AKS cluster name"
            type = "string"
            default = "15k"
        }
        ap.Parameter {
            name = "user_pool_vm_size"
            displayName = "User node pool VM size"
            type = "string"
            default = "Standard_D4s_v3"
        }
        ap.Parameter {
            name = "network_dataplane"
            displayName = "Network dataplane (leave empty for AKS default)"
            type = "string"
            default = "cilium"
        }
    ]

    variables = {
        subscription_id = "\${{ parameters.subscription_id }}"
        location = "\${{ parameters.location }}"
        cluster_name = "\${{ parameters.cluster_name }}"
        user_pool_vm_size = "\${{ parameters.user_pool_vm_size }}"
        network_dataplane = "\${{ parameters.network_dataplane }}"
    }

    jobs = [
        job.Job {
            job = "create_cluster"
            displayName = "Create 15K Nodes Cluster"
            timeoutInMinutes = 600

            steps = [
                azure.Login(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                common.SetRunId(),
                azure.CreateResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    "SkipAKSCluster=true"
                ),
                azure.CreateManagedIdentity(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    IDENTITY_NAME
                ),
                azure.CreateVNet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "10.0.0.0/8",
                    SUBSCRIPTION_ID,
                    "$(IDENTITY_PRINCIPAL_ID)"
                ),
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "nodes",
                    "10.1.0.0/18",
                    SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "apiserver",
                    "10.240.0.0/28",
                    SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "AzureFirewallSubnet",
                    "10.2.0.0/16",
                    SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "jumpbox",
                    "10.3.0.0/16",
                    SUBSCRIPTION_ID
                ),
                azure.SetupFirewallForSubnet(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    LOCATION,
                    FW_NAME,
                    VNET_NAME,
                    "nodes",
                    "$(Pipeline.Workspace)/s/kcl/ccp_team/15K_cluster/firewall-policy.json"
                ),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Create jumpbox",
                    createJumpboxScript
                ),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Create AKS cluster",
                    createClusterScript
                ),
                azure.WaitForClusterSucceeded(
                    SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID
                ),
                *[azure.CreateNodePool(
                    SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    pool
                ) for pool in _userPools],
            ]
        }
    ]
}
