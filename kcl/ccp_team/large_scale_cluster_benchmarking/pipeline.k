import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common

SUBSCRIPTION_ID = "\${{ parameters.subscription_id }}"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "\${{ parameters.location }}"
CLUSTER_NAME = "large-scale"
SERVICE_CONNECTION = "$(AZURE_SERVICE_CONNECTION)"
VNET_NAME = "${CLUSTER_NAME}-net"
JUMPBOX_NAME = "${CLUSTER_NAME}-jumpbox"

# Keep each pool at 800 nodes to leave capacity for max-surge nodes during upgrades.
MAX_NODES_PER_POOL = 800

createClusterScript = """
az extension add --name aks-preview --allow-preview true --upgrade --yes

CREATE_ARGS=(
  --subscription "${SUBSCRIPTION_ID}"
  --resource-group "${RESOURCE_GROUP}"
  --name "${CLUSTER_NAME}"
  --location "${LOCATION}"
  --kubernetes-version "1.37"
  --dns-name-prefix "${CLUSTER_NAME}-dns"
  --tier standard
  --assign-identity "$(createManagedIdentity.IDENTITY_ID)"
  --tags SkipAKSCluster=true
  --control-plane-scaling-size H2
  --nodepool-name system
  --node-count 2
  --node-vm-size Standard_D16ds_v5
  --max-pods 60
  --os-sku Ubuntu
  # AKS nodes enable THP by default, but the test VMs have limited memory.
  # Disable THP to avoid excessive node memory usage affecting benchmark results.
  --linux-os-config "$(Pipeline.Workspace)/s/kcl/ccp_team/large_scale_cluster_benchmarking/manifests/linux-os-config.json"
  --vnet-subnet-id "$(createSubnet_nodes.NODES_SUBNET_ID)"
  --network-plugin azure
  --network-plugin-mode overlay
  --pod-cidr 10.0.0.0/8
  --service-cidr 192.168.0.0/16
  --dns-service-ip 192.168.0.10
  --outbound-type userDefinedRouting
  --enable-private-cluster
  --auto-upgrade-channel none
  --node-os-upgrade-channel None
  --generate-ssh-keys
  --yes
)
[[ "\${{ parameters.network_dataplane }}" != "none" ]] && CREATE_ARGS+=(--network-dataplane "\${{ parameters.network_dataplane }}")

# Azure Pipelines renders boolean parameters as True or False, so compare case-insensitively.
[[ "\${{ parameters.enable_apiserver_vnet_integration }}" == [Tt][Rr][Uu][Ee] ]] && CREATE_ARGS+=(--enable-apiserver-vnet-integration --apiserver-subnet-id "$(createSubnet_apiserver.APISERVER_SUBNET_ID)")

KEY_ID="\${{ parameters.kms_key_id }}"
# Infrastructure encryption enables KMS v2 Plus.
if [ "$KEY_ID" != "none" ]; then
  CREATE_ARGS+=(
    --enable-azure-keyvault-kms
    --azure-keyvault-kms-key-id "$KEY_ID"
    --kms-infrastructure-encryption Enabled
  )
fi

az aks create "\${CREATE_ARGS[@]}"
"""

output = ap.Pipeline {
    name = "Large Scale Cluster Creation"

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
            name = "user_pool_vm_size"
            displayName = "User node pool VM size"
            type = "string"
            default = "Standard_D4s_v3"
        }
        ap.Parameter {
            name = "user_total_nodes"
            displayName = "Total user nodes"
            type = "number"
            default = 14997
        }
        ap.Parameter {
            name = "network_dataplane"
            displayName = "Network dataplane (use 'none' to omit --network-dataplane)"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "enable_apiserver_vnet_integration"
            displayName = "Enable API server VNet integration"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "kms_key_id"
            displayName = "KMS key ID (versioned Key Vault key URI; 'none' to disable)"
            type = "string"
            default = "none"
        }
    ]

    jobs = [
        job.Job {
            job = "create_cluster"
            displayName = "Create Large Scale Cluster"
            timeoutInMinutes = 1440
            # Leave time for the always() cleanup step to delete the cluster after cancellation or timeout.
            cancelTimeoutInMinutes = 120

            steps = [
                steps.Bash {
                    # Azure CNI Overlay assigns a /24 per node, so the 10.0.0.0/8 pod CIDR fits 65536
                    # nodes. Reserve 3 for the system and CL2 pools and one user pool's worth for upgrade surge.
                    bash = """
set -eo pipefail
total_nodes="\${{ parameters.user_total_nodes }}"
max_total_nodes=${65536 - 3 - MAX_NODES_PER_POOL}
if [ "$total_nodes" -gt "$max_total_nodes" ]; then
  echo "user_total_nodes=$total_nodes exceeds the pod CIDR capacity of $max_total_nodes nodes."
  exit 1
fi
"""
                    displayName = "Validate total user nodes"
                },
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
                    "${CLUSTER_NAME}-identity"
                ),
                azure.CreateVNet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "172.16.0.0/12",
                    SUBSCRIPTION_ID,
                    "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)"
                ),
                # Generated step name: createSubnet_nodes
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "nodes",
                    "172.16.0.0/14",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_apiserver
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "apiserver",
                    "172.20.0.0/28",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_AzureFirewallSubnet
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "AzureFirewallSubnet",
                    "172.21.0.0/16",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_jumpbox
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "jumpbox",
                    "172.22.0.0/16",
                    SUBSCRIPTION_ID
                ),
                azure.SetupFirewallForSubnet(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    LOCATION,
                    "${CLUSTER_NAME}-firewall",
                    VNET_NAME,
                    "nodes",
                    "$(Pipeline.Workspace)/s/kcl/ccp_team/large_scale_cluster_benchmarking/manifests/firewall-policy.json",
                    minCapacity="45",
                    maxCapacity="45"
                ),
                azure.CreateJumpbox(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    JUMPBOX_NAME,
                    VNET_NAME,
                    vmSize = "Standard_D4ds_v5"
                ),
                azure.GrantKeyVaultCryptoUser(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    "\${{ parameters.kms_key_id }}",
                    "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)",
                    condition = "ne('\${{ parameters.kms_key_id }}', 'none')"
                ),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Create AKS cluster",
                    createClusterScript
                ),
                # Dedicated tainted pool so the CL2 runner does not share nodes with system add-ons
                # or benchmark workloads.
                azure.CreateNodePool(
                    SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    azure.NodePool {
                        name = "cl2"
                        sku = "Standard_D48ds_v5"
                        count = 1
                        taintPrefix = "cl2"
                        vnetSubnetId = "$(createSubnet_nodes.NODES_SUBNET_ID)"
                        osSKU = "Ubuntu"
                    }
                ),
                azure.CreateNodePoolsFromPipelineParameter(
                    SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "\${{ parameters.user_pool_vm_size }}",
                    "\${{ parameters.user_total_nodes }}",
                    MAX_NODES_PER_POOL,
                    vnetSubnetId = "$(createSubnet_nodes.NODES_SUBNET_ID)",
                    osSKU = "Ubuntu",
                    # AKS nodes enable THP by default, but the test VMs have limited memory.
                    # Disable THP on all node pools to avoid excessive node memory usage affecting benchmark results.
                    linuxOsConfig = "$(Pipeline.Workspace)/s/kcl/ccp_team/large_scale_cluster_benchmarking/manifests/linux-os-config.json"
                ),
                azure.RunScriptOnJumpbox(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    JUMPBOX_NAME,
                    "Configure kubeconfig on jumpbox ${JUMPBOX_NAME}",
                    """
az login --identity --output none
az account set --subscription "${SUBSCRIPTION_ID}"
az aks get-credentials \\
  --admin \\
  --overwrite-existing \\
  --file /var/tmp/telescope-kubeconfig \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${CLUSTER_NAME}" \\
  --subscription "${SUBSCRIPTION_ID}"
chmod 600 /var/tmp/telescope-kubeconfig
test -s /var/tmp/telescope-kubeconfig
"""
                ),
                *azure.RunClusterLoader2OnJumpbox(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    JUMPBOX_NAME,
                    "kcl/ccp_team/large_scale_cluster_benchmarking/manifests/cl2.yaml"
                ),
                azure.RunScriptOnJumpbox(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    JUMPBOX_NAME,
                    "Collect ClusterLoader2 results and check success",
                    """
export KUBECONFIG=/var/tmp/telescope-kubeconfig
pods=$(kubectl get pods \\
  --namespace="clusterloader2" \\
  --selector job-name=cl2 \\
  --output jsonpath='{.items[*].metadata.name}')
test -n "$pods"

for pod in $pods; do
  echo "===== Results for pod: $pod ====="
  kubectl logs \\
    --namespace="clusterloader2" \\
    "$pod" \\
    --container=cl2-results
done

# Collect all results before failing the step for an unsuccessful benchmark.
for pod in $pods; do
  pod_result=$(kubectl get pod "$pod" \\
    --namespace="clusterloader2" \\
    --output jsonpath='{.status.phase}:{.status.containerStatuses[?(@.name=="cl2")].state.terminated.exitCode}')
  if [ "$pod_result" != "Succeeded:0" ]; then
    echo "ClusterLoader2 pod $pod failed: phase:exitCode=$pod_result (expected Succeeded:0)"
    exit 1
  fi
done
"""
                ),
                azure.RevokeKeyVaultCryptoUser(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    "\${{ parameters.kms_key_id }}",
                    "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)",
                    condition = "and(always(), ne('\${{ parameters.kms_key_id }}', 'none'))"
                ),
                azure.DeleteResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID
                ),
            ]
        }
    ]
}
