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
  --node-count 3
  --node-vm-size Standard_D48ds_v5
  --max-pods 60
  --os-sku Ubuntu
  --vnet-subnet-id "$(createSubnet_nodes.NODES_SUBNET_ID)"
  --network-plugin azure
  --network-plugin-mode overlay
  --pod-cidr 10.64.0.0/10
  --outbound-type userDefinedRouting
  --enable-private-cluster
  --auto-upgrade-channel none
  --node-os-upgrade-channel None
  --generate-ssh-keys
  --yes
)
[[ "$(network_dataplane)" != "none" ]] && CREATE_ARGS+=(--network-dataplane "$(network_dataplane)")

# Azure Pipelines exposes boolean parameters as string variables, so accept either True or true.
[[ "$(enable_apiserver_vnet_integration)" == [Tt][Rr][Uu][Ee] ]] && CREATE_ARGS+=(--enable-apiserver-vnet-integration --apiserver-subnet-id "$(createSubnet_apiserver.APISERVER_SUBNET_ID)")

KEY_ID="$(kms_key_id)"
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

grantKmsAccessScript = """
KEY_ID="$(kms_key_id)"
if ! [[ "$KEY_ID" =~ ^https://([^/]+)/keys/[^/]+/[^/]+$ ]]; then
  echo "kms_key_id must be a versioned Key Vault key URI, or 'none' to disable KMS."
  exit 1
fi
HOST="\${KEY_ID#https://}"
VAULT_NAME="\${HOST%%.*}"

KEY_VAULT_RESOURCE_ID=$(az keyvault show \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --name "$VAULT_NAME" \\
  --query id -o tsv)

az role assignment create \\
  --role "Key Vault Crypto User" \\
  --assignee-object-id "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)" \\
  --assignee-principal-type ServicePrincipal \\
  --scope "$KEY_VAULT_RESOURCE_ID"
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
            name = "cluster_name"
            displayName = "AKS cluster name"
            type = "string"
            default = "large-scale"
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

    variables = {
        subscription_id = "\${{ parameters.subscription_id }}"
        location = "\${{ parameters.location }}"
        cluster_name = "\${{ parameters.cluster_name }}"
        user_pool_vm_size = "\${{ parameters.user_pool_vm_size }}"
        user_total_nodes = "\${{ parameters.user_total_nodes }}"
        network_dataplane = "\${{ parameters.network_dataplane }}"
        enable_apiserver_vnet_integration = "\${{ parameters.enable_apiserver_vnet_integration }}"
        kms_key_id = "\${{ parameters.kms_key_id }}"
    }

    jobs = [
        job.Job {
            job = "create_cluster"
            displayName = "Create Large Scale Cluster"
            timeoutInMinutes = 1440

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
                    "${CLUSTER_NAME}-identity"
                ),
                azure.CreateVNet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "10.0.0.0/8",
                    SUBSCRIPTION_ID,
                    "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)"
                ),
                # Generated step name: createSubnet_nodes
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "nodes",
                    "10.1.0.0/18",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_apiserver
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "apiserver",
                    "10.240.0.0/28",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_AzureFirewallSubnet
                azure.CreateSubnet(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    VNET_NAME,
                    "AzureFirewallSubnet",
                    "10.2.0.0/16",
                    SUBSCRIPTION_ID
                ),
                # Generated step name: createSubnet_jumpbox
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
                    vmSize = "Standard_D32ds_v5"
                ),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Grant KMS access to cluster identity",
                    grantKmsAccessScript,
                    condition = "ne(variables['kms_key_id'], 'none')"
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
                azure.CreateNodePoolsFromPipelineParameter(
                    SERVICE_CONNECTION,
                    CLUSTER_NAME,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "$(user_pool_vm_size)",
                    "\${{ parameters.user_total_nodes }}",
                    MAX_NODES_PER_POOL,
                    vnetSubnetId = "$(createSubnet_nodes.NODES_SUBNET_ID)",
                    osSKU = "Ubuntu"
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
                # AKS node VMs have THP enabled by default, but the VMs available for testing
                # have limited memory. Disable THP to avoid excessive node memory usage
                # affecting benchmark results.
                *azure.ApplyManifestOnJumpbox(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    RESOURCE_GROUP,
                    JUMPBOX_NAME,
                    "kcl/ccp_team/large_scale_cluster_benchmarking/manifests/disable-thp.yaml"
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
                    "Print ClusterLoader2 results",
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
"""
                ),
                azure.DeleteResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    condition = "succeeded()"
                ),
            ]
        }
    ]
}
