import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure

SUBSCRIPTION_ID = "$(subscription_id)"
RESOURCE_GROUP = "$(resource_group)"
LOCATION = "$(location)"
CLUSTER_NAME = "$(cluster_name)"
K8S_VERSION = "1.33.0"

VNET_NAME = "${CLUSTER_NAME}-net"
IDENTITY_NAME = "${CLUSTER_NAME}-identity"
FW_PUBLIC_IP_NAME = "${CLUSTER_NAME}-firewall-pip"
FW_NAME = "${CLUSTER_NAME}-firewall"
RT_NAME = "${CLUSTER_NAME}-rt"
JUMPBOX_NAME = "${CLUSTER_NAME}-jumpbox"

VNET_CIDR = "10.0.0.0/8"
NODES_SUBNET_CIDR = "10.1.0.0/18"
APISERVER_SUBNET_CIDR = "10.240.0.0/28"
FIREWALL_SUBNET_CIDR = "10.2.0.0/16"
JUMPBOX_SUBNET_CIDR = "10.3.0.0/16"

USER_TOTAL_NODES = 14997    # KCL constant: change here to adjust total
MAX_NODES_PER_POOL = 800    # KCL constant: change here to adjust split

_userPools = [azure.NodePool {
    name = pool.name
    sku = pool.sku
    count = pool.count
    vnetSubnetId = "$(NODE_SUBNET_ID)"
    osSKU = "Ubuntu"
} for pool in azure.PlanNodePools({"$(user_pool_vm_size)": USER_TOTAL_NODES}, MAX_NODES_PER_POOL)]


createClusterScript = """
cat > /tmp/aks-body.json << EOF
{
  "location": "${LOCATION}",
  "sku": {"name": "Base", "tier": "Standard"},
  "identity": {
    "type": "UserAssigned",
    "userAssignedIdentities": {"$(IDENTITY_ID)": {}}
  },
  "tags": {
    "SkipAKSCluster": "true",
    "SkipASMAzSecPackAutoConfig": "true",
    "SkipLinuxAzSecPack": "true",
    "exempted_by_qi": "36344494"
  },
  "properties": {
    "controlPlaneScalingProfile": {"scalingSize": "H8"},
    "kubernetesVersion": "${K8S_VERSION}",
    "dnsPrefix": "${CLUSTER_NAME}-dns",
    "agentPoolProfiles": [
      {
        "name": "system",
        "count": 10,
        "vmSize": "Standard_D48s_v3",
        "maxPods": 60,
        "osType": "Linux",
        "osSKU": "Ubuntu",
        "mode": "System",
        "vnetSubnetID": "$(NODE_SUBNET_ID)"
      }
    ],
    "networkProfile": {
      "networkPlugin": "azure",
      "networkPluginMode": "overlay",
      "networkDataplane": "cilium",
      "podCidr": "10.64.0.0/10",
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
    name = "15K Cilium VNet Cluster Creation"

    trigger = "none"
    pool = const.DEFAULT_POOL

    variables = {
        subscription_id = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
        resource_group = "xinwei-15k-cilium-vnet"
        location = "eastasia"
        cluster_name = "15k-private-cluster"
        user_pool_vm_size = "Standard_D4s_v3"
    }

    jobs = [
        job.Job {
            job = "create_cluster"
            displayName = "Create 15K Cilium Private Cluster"
            timeoutInMinutes = 600

            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    "SkipAKSCluster=true exempted_by_qi=36344494"
                ),
                azure.CreateManagedIdentity(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    IDENTITY_NAME,
                    SUBSCRIPTION_ID
                ),
                azure.CreateVNet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    VNET_CIDR,
                    SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "nodes", NODES_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "NODE_SUBNET_ID"
                ),
                azure.CreateRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(NODE_SUBNET_ID)", "Network Contributor",
                    "$(IDENTITY_CLIENT_ID)", SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "apiserver", APISERVER_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "APISERVER_SUBNET_ID"
                ),
                azure.CreateRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(APISERVER_SUBNET_ID)", "Network Contributor",
                    "$(IDENTITY_CLIENT_ID)", SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "AzureFirewallSubnet", FIREWALL_SUBNET_CIDR,
                    SUBSCRIPTION_ID, "FIREWALL_SUBNET_ID"
                ),
                azure.CreateRoleAssignment(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(FIREWALL_SUBNET_ID)", "Network Contributor",
                    "$(IDENTITY_CLIENT_ID)", SUBSCRIPTION_ID
                ),
                azure.CreateSubnet(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "jumpbox", JUMPBOX_SUBNET_CIDR,
                    SUBSCRIPTION_ID
                ),
                azure.CreateFirewall(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, FW_NAME, LOCATION,
                    VNET_NAME, FW_PUBLIC_IP_NAME, SUBSCRIPTION_ID
                ),
                azure.CreateRouteTable(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, RT_NAME, LOCATION,
                    SUBSCRIPTION_ID
                ),
                azure.CreateRoute(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, RT_NAME,
                    "egress", "0.0.0.0/0",
                    "VirtualAppliance", "$(FWPRIVATE_IP)",
                    SUBSCRIPTION_ID
                ),
                azure.AssociateRouteTable(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, VNET_NAME,
                    "nodes", RT_NAME, SUBSCRIPTION_ID
                ),
                azure.UpdateFirewallPolicy(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP, FW_NAME, SUBSCRIPTION_ID,
                    "$(Pipeline.Workspace)/s/kcl/ccp_team/15K_cluster/firewall-policy.json",
                    LOCATION
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
