import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common

SUBSCRIPTION_ID = "$(subscription_id)"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "$(location)"
CLUSTER_NAME = "$(cluster_name)"
K8S_VERSION = "1.33.0"

VNET_NAME = "${CLUSTER_NAME}-net"
IDENTITY_NAME = "${CLUSTER_NAME}-identity"
FW_NAME = "${CLUSTER_NAME}-firewall"
JUMPBOX_NAME = "${CLUSTER_NAME}-jumpbox"

VNET_CIDR = "10.0.0.0/8"
NODES_SUBNET_CIDR = "10.1.0.0/18"
APISERVER_SUBNET_CIDR = "10.240.0.0/28"
FIREWALL_SUBNET_CIDR = "10.2.0.0/16"
JUMPBOX_SUBNET_CIDR = "10.3.0.0/16"

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
NETWORK_DATAPLANE_JSON_FIELD=""
if [ -n "$NETWORK_DATAPLANE" ]; then
  NETWORK_DATAPLANE_JSON_FIELD='"networkDataplane": "'"$NETWORK_DATAPLANE"'",'
fi

cat > /tmp/aks-body.json << EOF
{
  "location": "${LOCATION}",
  "sku": {"name": "Base", "tier": "Standard"},
  "identity": {
    "type": "UserAssigned",
    "userAssignedIdentities": {"$(IDENTITY_ID)": {}}
  },
  "tags": {
    "SkipAKSCluster": "true"
  },
  "properties": {
    "controlPlaneScalingProfile": {"scalingSize": "H8"},
    "kubernetesVersion": "${K8S_VERSION}",
    "dnsPrefix": "${CLUSTER_NAME}-dns",
    "agentPoolProfiles": [
      {
        "name": "system",
        "count": 3,
        "vmSize": "Standard_D48s_v3",
        "maxPods": 60,
        "osType": "Linux",
        "osSKU": "Ubuntu",
        "mode": "System",
        "vnetSubnetID": "$(NODES_SUBNET_ID)"
      }
    ],
    "networkProfile": {
      "networkPlugin": "azure",
      "networkPluginMode": "overlay",
      "podCidr": "10.64.0.0/10",
      \${NETWORK_DATAPLANE_JSON_FIELD}
      "outboundType": "userDefinedRouting"
    },
    "apiServerAccessProfile": {
      "enablePrivateCluster": true,
      "enableVnetIntegration": true,
      "subnetId": "$(APISERVER_SUBNET_ID)"
    }
  }
}
EOF

az rest \\
  --method put \\
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER_NAME}?api-version=2026-01-02-preview" \\
  --headers "Content-Type=application/json" \\
  --body "@/tmp/aks-body.json"
"""

output = ap.Pipeline {
    name = "15K Nodes Cluster Creation"

    trigger = "none"
    pool = const.DEFAULT_POOL

    variables = {
        subscription_id = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
        location = "eastasia"
        cluster_name = "15k"
        user_pool_vm_size = "Standard_D4s_v3"
        network_dataplane = "cilium"
    }

    jobs = [
        job.Job {
            job = "create_cluster"
            displayName = "Create 15K Nodes Cluster"
            timeoutInMinutes = 600

            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                common.SetRunId(),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    "SkipAKSCluster=true"
                ),
                azure.CreateManagedIdentity(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    IDENTITY_NAME
                ),
                azure.CreateVNet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    VNET_CIDR,
                    SUBSCRIPTION_ID
                ),
                azure.CreateSubnetAndRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "nodes", NODES_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "$(IDENTITY_CLIENT_ID)"
                ),
                azure.CreateSubnetAndRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "apiserver", APISERVER_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "$(IDENTITY_CLIENT_ID)"
                ),
                azure.CreateSubnetAndRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "AzureFirewallSubnet", FIREWALL_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "$(IDENTITY_CLIENT_ID)"
                ),
                azure.CreateSubnetAndRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "jumpbox", JUMPBOX_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "$(IDENTITY_CLIENT_ID)"
                ),
                azure.SetupFirewallForSubnet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID, RESOURCE_GROUP, LOCATION,
                    FW_NAME, VNET_NAME, "nodes",
                    "$(Pipeline.Workspace)/s/kcl/ccp_team/15K_cluster/firewall-policy.json"
                ),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create jumpbox",
                    createJumpboxScript
                ),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create AKS cluster",
                    createClusterScript
                ),
                azure.WaitForClusterSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID
                ),
                *[azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    pool
                ) for pool in _userPools],
            ]
        }
    ]
}
