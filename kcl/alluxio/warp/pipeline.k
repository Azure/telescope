import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.alluxio
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

# Replace these constants with the existing registry and staged image/chart repositories.
ACR_RESOURCE_ID = "REPLACE_ME_ACR_RESOURCE_ID"
ALLUXIO_IMAGE_REPOSITORY = "REPLACE_ME.azurecr.io/alluxio-enterprise"
OPERATOR_IMAGE_REPOSITORY = "REPLACE_ME.azurecr.io/alluxio-operator"
OPERATOR_CHART_REPOSITORY = "oci://REPLACE_ME.azurecr.io/helm/alluxio-operator"
LOCATION = "westeurope"
RESOURCE_GROUP = "alluxio-$(RUN_ID)-$(System.JobAttempt)"
CLUSTER = "alluxio-warp"
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
            alluxio.PrepareRun(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_RESOURCE_ID
                ALLUXIO_IMAGE_REPOSITORY
                OPERATOR_IMAGE_REPOSITORY
                OPERATOR_CHART_REPOSITORY
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                LOCATION
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
                file = "${WORK_DIR}/kubeconfig"
            )
            alluxio.GrantImagePullAccess(
                const.DEFAULT_SERVICE_CONNECTION
                WORK_DIR
                RESULT_DIR
            )
            alluxio.SeedWarpDataset(
                const.DEFAULT_SERVICE_CONNECTION
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            alluxio.InstallOperator(
                const.DEFAULT_SERVICE_CONNECTION
                OPERATOR_CHART_REPOSITORY
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateAlluxioCluster(
                WORK_DIR
                RESULT_DIR
            )
            alluxio.MountBlobStorage(
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateWarpClient(
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
                env = {
                    WORK_DIR = WORK_DIR
                    RESULT_DIR = RESULT_DIR
                    KUBECONFIG = "${WORK_DIR}/kubeconfig"
                }
                bash = alluxio.ShellSetup(WORK_DIR, RESULT_DIR) + """
if [[ ! -f "$work_dir/kubeconfig" ]]; then
    echo '{"cluster_access":"not established"}' > "$result_dir/diagnostics.json"
    exit 0
fi
for namespace in alx-ns alluxio-operator; do
    kubectl get pods -n "$namespace" -o json |
        jq --arg namespace "$namespace" '{
            ($namespace): [.items[] | {
                name: .metadata.name, node: .spec.nodeName, phase: .status.phase,
                containers: [(.status.containerStatuses // []) + (.status.initContainerStatuses // []) | .[] |
                    {name, ready, restarts: .restartCount,
                     state: (.state | with_entries(.value |= {reason, exitCode}))}]
            }]
        }' > "$work_dir/diagnostics-$namespace.json"
done
jq -s 'add' "$work_dir/diagnostics-alx-ns.json" "$work_dir/diagnostics-alluxio-operator.json" \\
    > "$result_dir/diagnostics.json"
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
                WORK_DIR
                RESULT_DIR
            )
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                condition = "and(always(), eq(variables['alluxio_setup.READY_FOR_PROVISIONING'], 'true'))"
            )
        ]
    }]
}
