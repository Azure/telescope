import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common

LOCATION = "australiaeast"
RESOURCE_GROUP = "acr-five-pulls-$(RUN_ID)"
CLUSTER = "acr-five-pulls"
WORKER_POOL = "pullpool"
SCENARIO = "$(Build.SourcesDirectory)/kcl/acr_benchmark/elastic_storage_five_pulls"
RESULT_DIRECTORY = "$(Pipeline.Workspace)/acr-five-pulls-results"
KUBECONFIG = "$(Agent.TempDirectory)/acr-five-pulls-$(RUN_ID).kubeconfig"
SSH_KEY = "$(Agent.TempDirectory)/acr-five-pulls-$(RUN_ID)"
# test1gb:latest resolved on 2026-10-18; all five nodes pull the same content.
IMAGE = "williamjcusaue1.azurecr-test.io/test1gb@sha256:bec0623e6590d7fe14c2ccb62a0049bfc0386a0e0fe35969f733077f31e7eea4"

credentialEnv = {
    ACR_PULL_USERNAME = "williamjcusaue1"
    ACR_PULL_PASSWORD = "$(ACR_PULL_PASSWORD)"
}

output = ap.Pipeline {
    name = "ACR Kubernetes Five Cold Pulls"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    jobs = [job.Job {
        job = "five_cold_pulls"
        displayName = "Pull test1gb on five fresh AKS workers"
        timeoutInMinutes = 120
        cancelTimeoutInMinutes = 15
        steps = [
            common.SetRunId()
            steps.Bash {
                displayName = "Validate credentials and prepare local files"
                env = {
                    **credentialEnv
                    RESULT_DIRECTORY = RESULT_DIRECTORY
                    SSH_KEY = SSH_KEY
                }
                bash = """
set -euo pipefail
mkdir -p "$RESULT_DIRECTORY"
python3 "${SCENARIO}/pull.py" check-credentials
ssh-keygen -q -t rsa -b 3072 -N "" -f "$SSH_KEY"
"""
            }
            azure.Login(const.DEFAULT_SERVICE_CONNECTION, const.DEFAULT_SUBSCRIPTION_ID, LOCATION)
            azure.AzCli(const.DEFAULT_SERVICE_CONNECTION, "Create an isolated test resource group", """
if [ "$(az group exists --name "${RESOURCE_GROUP}" --subscription "${const.DEFAULT_SUBSCRIPTION_ID}")" != "false" ]; then
  echo "##[error]Refusing to use an existing resource group: ${RESOURCE_GROUP}"
  exit 1
fi
az group create \\
  --name "${RESOURCE_GROUP}" \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --tags "SkipAKSCluster=1" "run_id=$(RUN_ID)" \\
  --output none
set +x
echo "##vso[task.setvariable variable=created;isOutput=true]true"
""", stepName="create_test_group")
            azure.AzCli(const.DEFAULT_SERVICE_CONNECTION, "Create AKS with one system node", """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --tier standard \\
  --nodepool-name systempool \\
  --nodepool-taints CriticalAddonsOnly=true:NoSchedule \\
  --node-count 1 \\
  --node-vm-size Standard_D4ds_v5 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --enable-managed-identity \\
  --ssh-key-value "${SSH_KEY}.pub" \\
  --output none
""")
            azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, const.DEFAULT_SUBSCRIPTION_ID, azure.NodePool {
                name = WORKER_POOL
                sku = "Standard_D4ds_v5"
                count = 5
                taintPrefix = "acrpull"
                labels = "benchmark=acr-five-pulls"
            })
            azure.GetCredentials(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, const.DEFAULT_SUBSCRIPTION_ID, KUBECONFIG)
            steps.Bash {
                displayName = "Pull the pinned image once on each worker"
                env = {
                    **credentialEnv
                    KUBECONFIG = KUBECONFIG
                }
                bash = """
set -euo pipefail
python3 "${SCENARIO}/pull.py" run \\
  --image "${IMAGE}" \\
  --node-pool "${WORKER_POOL}" \\
  --output "${RESULT_DIRECTORY}/results.json" \\
  --run-id "$(RUN_ID)" \\
  --run-url "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)" \\
  --pipeline "$(Build.DefinitionName)"
"""
            }
            steps.Task {
                task = "PublishPipelineArtifact@1"
                displayName = "Publish image-pull results"
                condition = "always()"
                inputs = {
                    targetPath = RESULT_DIRECTORY
                    artifact = "acr-five-pulls"
                }
            }
            azure.DeleteResourceGroup(const.DEFAULT_SERVICE_CONNECTION, RESOURCE_GROUP, const.DEFAULT_SUBSCRIPTION_ID, condition="and(always(), eq(variables['create_test_group.created'], 'true'))")
            steps.Bash {
                displayName = "Remove local kubeconfig and SSH key"
                condition = "always()"
                env = {
                    KUBECONFIG = KUBECONFIG
                    SSH_KEY = SSH_KEY
                }
                bash = """
set -euo pipefail
rm -f -- "$KUBECONFIG" "$SSH_KEY" "$SSH_KEY.pub"
"""
            }
        ]
    }]
}
