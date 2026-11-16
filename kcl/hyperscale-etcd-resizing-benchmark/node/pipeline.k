import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util.asi_dashboard

NODE_COUNT = 30000
LOCATION = "eastasia"
CLUSTER = "node-$(Build.BuildId)-$(System.JobAttempt)"
RESOURCE_GROUP = "rg-${CLUSTER}"

createClusterScript = """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes

az aks create \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${CLUSTER}" \\
  --location "${LOCATION}" \\
  --kubernetes-version 1.35.0 \\
  --tier standard \\
  --generate-ssh-keys \\
  --nodepool-name systempool \\
  --node-count 6 \\
  --node-vm-size Standard_D8s_v3 \\
  --tags SkipAKSCluster=true \\
  --control-plane-scaling-size H8 \\
  --yes
"""

output = ap.Pipeline {
    name = "Hyperscale etcd Nodes partition sizing"
    trigger = "none"
    pool = const.DEFAULT_POOL
    jobs = [
        job.Job {
            job = "node_etcd_partition_resizing"
            timeoutInMinutes = 360
            steps = [
                common.InstallPythonDependencies(),
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    const.DEFAULT_SUBSCRIPTION_ID,
                    LOCATION),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    const.DEFAULT_SUBSCRIPTION_ID),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create AKS cluster (etcd)",
                    createClusterScript),
                azure.WaitForClusterSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID,
                    azure.NodePool {
                        name = "workerpool"
                        sku = "Standard_D8s_v3"
                        count = 150
                    }),
                common.RecordCurrentTime("BENCHMARK_START"),
                *k8s.CreateKwokNodes(
                    NODE_COUNT,
                    params = {
                        "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_apiserver_executing_seats/kwok-node.yaml"
                        "node-create-workers": "30"
                    }),
                steps.Bash {
                    displayName = "Wait 60 minutes for default KWOK updates"
                    bash = "sleep 3600"
                },
                k8s.DeleteKwokNodes(NODE_COUNT),
                steps.Bash {
                    displayName = "Wait 10 minutes after deletion"
                    bash = "sleep 600"
                },
                asi_dashboard.PrintAsiDashboardUrl(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID,
                    "$(BENCHMARK_START)"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID,
                    condition = "always()"),
            ]
        },
    ]
}
