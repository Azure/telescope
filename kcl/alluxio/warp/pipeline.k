import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.alluxio
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

# Replace these constants with the existing registry and staged image/chart repositories.
ACR_RESOURCE_ID = "/subscriptions/REPLACE_ME_SUBSCRIPTION_ID/resourceGroups/REPLACE_ME_RESOURCE_GROUP/providers/Microsoft.ContainerRegistry/registries/REPLACE_ME_REGISTRY"
ACR_SUBSCRIPTION_ID = ACR_RESOURCE_ID.split("/")[2]
ALLUXIO_IMAGE_REPOSITORY = "REPLACE_ME.azurecr.io/alluxio-enterprise"
OPERATOR_IMAGE_REPOSITORY = "REPLACE_ME.azurecr.io/alluxio-operator"
OPERATOR_CHART_REPOSITORY = "oci://REPLACE_ME.azurecr.io/helm/alluxio-operator"
LOCATION = "westeurope"
RESOURCE_GROUP = "alluxio-$(RUN_ID)-$(System.JobAttempt)"
CLUSTER = "alluxio-warp"
STORAGE_ACCOUNT = "alx$(Build.BuildId)a$(System.JobAttempt)"
WORK_DIR = "$(Agent.TempDirectory)/alluxio-$(System.JobId)-$(System.JobAttempt)"
RESULT_DIR = "$(Build.ArtifactStagingDirectory)/alluxio-warp"
CHECKS_DIR = "$(Build.SourcesDirectory)/kcl/alluxio/warp"

output = ap.Pipeline {
    name = "Alluxio Warp Azure Blob"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    jobs = [job.Job {
        job = "alluxio_warp"
        displayName = "Alluxio Warp GET over Azure Blob"
        timeoutInMinutes = 180
        cancelTimeoutInMinutes = 30
        steps = [
            common.SetRunId()
            k8s.InstallHelm()
            alluxio.RecordRunConfiguration(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_RESOURCE_ID
                ACR_SUBSCRIPTION_ID
                ALLUXIO_IMAGE_REPOSITORY
                OPERATOR_IMAGE_REPOSITORY
                OPERATOR_CHART_REPOSITORY
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                LOCATION
                STORAGE_ACCOUNT
                WORK_DIR
                RESULT_DIR
            )
            azure.CreateResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                LOCATION
                const.DEFAULT_SUBSCRIPTION_ID
            )
            azure.AzCli(
                const.DEFAULT_SERVICE_CONNECTION
                "Create cluster"
                """
az aks create \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${CLUSTER}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size Standard_D8s_v5 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --enable-managed-identity \\
  --no-ssh-key \\
  --tier standard \\
  --yes
"""
            )
            # Separate worker/client nodes prevent the load generator competing with Alluxio.
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                azure.NodePool {
                    name = "workerpool"
                    sku = "Standard_D16s_v5"
                    count = 1
                    taintPrefix = "alluxio"
                }
            )
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                azure.NodePool {
                    name = "clientpool"
                    sku = "Standard_D8s_v5"
                    count = 1
                    taintPrefix = "warp"
                }
            )
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
            )
            alluxio.GrantImagePullAccess(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_RESOURCE_ID
                ACR_SUBSCRIPTION_ID
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                WORK_DIR
                RESULT_DIR
            )
            alluxio.SeedWarpDataset(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                LOCATION
                STORAGE_ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            alluxio.InstallOperator(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_RESOURCE_ID
                ACR_SUBSCRIPTION_ID
                OPERATOR_IMAGE_REPOSITORY
                OPERATOR_CHART_REPOSITORY
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateAlluxioCluster(
                ALLUXIO_IMAGE_REPOSITORY
                "${CHECKS_DIR}/cluster.yaml"
                "${CHECKS_DIR}/license.yaml"
                WORK_DIR
                RESULT_DIR
            )
            alluxio.MountBlobStorage(
                STORAGE_ACCOUNT
                "${CHECKS_DIR}/ufs.yaml"
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateWarpClient(
                "${CHECKS_DIR}/client.yaml"
                WORK_DIR
                RESULT_DIR
            )
            common.RecordCurrentTime("BENCHMARK_START_TIME")
            alluxio.RunWarpGet(
                "cold-start"
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            alluxio.PreloadAlluxioDataset(
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            alluxio.RunWarpGet(
                "warm-cache"
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            common.RecordCurrentTime("BENCHMARK_END_TIME")
            steps.Bash {
                name = "alluxio_diagnostics"
                displayName = "Collect safe deployment diagnostics"
                condition = "always()"
                bash = alluxio.ShellSetup(WORK_DIR, RESULT_DIR) + """
for namespace in alx-ns alluxio-operator; do
    kubectl get pods -n "$namespace" -o json |
        jq --arg namespace "$namespace" '{
            ($namespace): [.items[] | {
                name: .metadata.name, node: .spec.nodeName, phase: .status.phase,
                containers: [(.status.containerStatuses // []) + (.status.initContainerStatuses // []) | .[] |
                    {name, ready, restarts: .restartCount,
                     state: (.state | with_entries(.value |= {reason, exitCode}))}]
            }]
        }' > "${WORK_DIR}/diagnostics-$namespace.json"
done
jq -s 'add' "${WORK_DIR}/diagnostics-alx-ns.json" "${WORK_DIR}/diagnostics-alluxio-operator.json" \\
    > "${RESULT_DIR}/diagnostics.json"
"""
            }
            steps.Task {
                task = "PublishPipelineArtifact@1"
                displayName = "Publish Warp results and diagnostics"
                condition = "always()"
                inputs = {
                    targetPath = RESULT_DIR
                    artifact = "alluxio-warp-$(System.JobAttempt)"
                }
            }
            alluxio.RemoveImagePullAccess(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_RESOURCE_ID
                ACR_SUBSCRIPTION_ID
                WORK_DIR
                RESULT_DIR
            )
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
            )
        ]
    }]
}
