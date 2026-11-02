import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common

RESOURCE_GROUP = "$(RUN_ID)"
CLUSTER_NAME = "large-scale"
SERVICE_CONNECTION = "$(AZURE_SERVICE_CONNECTION)"
VNET_NAME = "${CLUSTER_NAME}-net"
JUMPBOX_NAME = "${CLUSTER_NAME}-jumpbox"

# Keep each pool at 800 nodes to leave capacity for max-surge nodes during upgrades.
MAX_NODES_PER_POOL = 800

# Test configuration. Change these values in a PR (or on a branch for ad-hoc runs) so the
# settings of every run are tracked in git.
SUBSCRIPTION_ID = "854c9ddb-fe9e-4aea-8d58-99ed88282881"
LOCATION = "canadacentral"
USER_POOL_VM_SIZE = "Standard_D4ds_v4"
USER_TOTAL_NODES = 14997
# Versioned Key Vault key URI used by the stages that enable KMS.
KMS_KEY_ID = "https://xinwei-15k-key-vault.vault.azure.net/keys/15k-test/38ca388db5e74ffab7b8ac920acf2a5b"

# Features toggled across stages. Every combination gets its own stage, so each run's
# configuration is defined in code.
schema Features:
    enableCiliumDataplane: bool
    enableApiserverVnetIntegration: bool
    enableKms: bool

createClusterScript = lambda features: Features -> str {
    optionalCreateArgs = "\n  ".join([f for f in [
        "--network-dataplane cilium" if features.enableCiliumDataplane else ""
        "--enable-apiserver-vnet-integration --apiserver-subnet-id \"$(createSubnet_apiserver.APISERVER_SUBNET_ID)\"" if features.enableApiserverVnetIntegration else ""
        # Infrastructure encryption enables KMS v2 Plus.
        "--enable-azure-keyvault-kms --azure-keyvault-kms-key-id \"${KMS_KEY_ID}\" --kms-infrastructure-encryption Enabled" if features.enableKms else ""
    ] if f])
    """
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
  --control-plane-scaling-size H8
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
  ${optionalCreateArgs}
)
az aks create "\${CREATE_ARGS[@]}"
"""
}

makeJob = lambda features: Features -> job.Job {
    job.Job {
        job = "create_cluster"
        displayName = "Create Large Scale Cluster"
        timeoutInMinutes = 1440
        # Leave time for the always() cleanup step to delete the cluster after cancellation or timeout.
        cancelTimeoutInMinutes = 120

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
            *([azure.GrantKeyVaultCryptoUser(
                SERVICE_CONNECTION,
                SUBSCRIPTION_ID,
                KMS_KEY_ID,
                "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)"
            )] if features.enableKms else []),
            azure.AzCli(
                SERVICE_CONNECTION,
                "Create AKS cluster",
                createClusterScript(features)
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
                }
            ),
            # AKS nodes enable THP by default, but the test VMs have limited memory.
            # Disable THP on all node pools to avoid excessive node memory usage affecting benchmark results.
            *[azure.CreateNodePool(
                SERVICE_CONNECTION,
                CLUSTER_NAME,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                azure.NodePool {
                    name = pool.name
                    sku = pool.sku
                    count = pool.count
                    vnetSubnetId = "$(createSubnet_nodes.NODES_SUBNET_ID)"
                    linuxOsConfig = "$(Pipeline.Workspace)/s/kcl/ccp_team/large_scale_cluster_benchmarking/manifests/linux-os-config.json"
                }
            ) for pool in azure.PlanNodePools({"${USER_POOL_VM_SIZE}" = USER_TOTAL_NODES}, MAX_NODES_PER_POOL)],
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
            *([azure.RevokeKeyVaultCryptoUser(
                SERVICE_CONNECTION,
                SUBSCRIPTION_ID,
                KMS_KEY_ID,
                "$(createManagedIdentity.IDENTITY_PRINCIPAL_ID)",
                condition = "always()"
            )] if features.enableKms else []),
            azure.DeleteResourceGroup(
                SERVICE_CONNECTION,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID
            ),
        ]
    }
}

# Name each stage by its enabled features, e.g. "cilium_kms", or "baseline" when none are enabled.
stageName = lambda features: Features -> str {
    enabled = [f[0] for f in [
        ["cilium", features.enableCiliumDataplane]
        ["apiserver_vnet", features.enableApiserverVnetIntegration]
        ["kms", features.enableKms]
    ] if f[1]]
    "_".join(enabled) if enabled else "baseline"
}

ALL_FEATURES = [
    Features {
        enableCiliumDataplane = cilium
        enableApiserverVnetIntegration = apiserverVnet
        enableKms = kms
    }
    for cilium in [False, True]
    for apiserverVnet in [False, True]
    for kms in [False, True]
]

output = ap.Pipeline {
    name = "Large Scale Cluster Creation"

    trigger = "none"
    pool = const.DEFAULT_POOL

    # Stages run one after another so only one large cluster exists at a time. not(canceled())
    # lets later stages run even when an earlier one fails or is not selected.
    stages = [
        ap.Stage {
            stage = stageName(f)
            displayName = "Cilium dataplane: ${f.enableCiliumDataplane}, API server VNet integration: ${f.enableApiserverVnetIntegration}, KMS: ${f.enableKms}"
            dependsOn = [stageName(ALL_FEATURES[i - 1])] if i > 0 else []
            condition = "not(canceled())"
            jobs = [makeJob(f)]
        }
        for i, f in ALL_FEATURES
    ]
}
