import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

# End-to-end example: stand up an AKS cluster with a dedicated image-pull node
# pool, then drive sustained registry blob-download traffic against an ACR stamp
# for a fixed duration using the RunImagePullLoad step (crictl pull -> rmi loop,
# one puller per node). See kcl/image_pull_load/image-pull-load.yaml for the
# load generator and lib/steps/k8s/run_image_pull_load.k for the step.
# ACR-team-specific values (overriding the Telescope const.k defaults).
# azurecontainerregistry-onprem-fc targets subscription dfb63c8c (ACR - Dev).
SERVICE_CONNECTION = "azurecontainerregistry-onprem-fc"
POOL = "Default"
SUBSCRIPTION_ID = "dfb63c8c-7c89-4ef8-af13-75c1d873c895"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "australiaeast"
CLUSTER = "image-pull-load"

# Dedicated pool(s) the pullers run on. The label/taint match the DaemonSet's
# nodeSelector + tolerations in image-pull-load.yaml.
PULL_POOL_LABEL = "cri-resource-consume=true"
PULL_POOL_TAINT_PREFIX = "cri-resource-consume"
PULL_POOL_SKU = "Standard_D4s_v3"

# Concurrency dial: one puller pod runs per node, so node count == puller count.
# Spread across multiple pools since a single AKS node pool caps out at 1000
# nodes; PlanNodePools splits this into pools of at most MAX_NODES_PER_POOL.
# NOTE: ensure regional vCPU quota covers PULL_POOL_NODE_COUNT * SKU cores
# (e.g. 1000 x Standard_D4s_v3 = 4000 vCPUs).
PULL_POOL_NODE_COUNT = 1000
MAX_NODES_PER_POOL = 800

PULL_NAMESPACE = "image-pull-load"
# Duration dial: how long to sustain the load (seconds). 1800 = 30 minutes.
LOAD_DURATION_SECONDS = 1800

# Image(s) under test. Space-separated, fully-qualified refs; list DISTINCT
# tags/digests to raise per-node concurrency.
PULL_IMAGE = "acrstampperftest.azurecr-test.io/test_10gb_4l_v1:latest"

# Result storage (ACR-team self-hosted Telescope v2 data infra, same sub as the
# service connection). The run-result.json is ingested into the ADX `results`
# table via Event Grid -> Event Hub. Shared-key auth is disabled by policy, so we
# upload with --auth-mode login; the service connection identity must hold the
# Storage Blob Data Contributor role on this account.
RESULT_STORAGE_ACCOUNT = "acrtelescoperesults"
RESULT_CONTAINER = "acr"

createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.35.0" \\
  --dns-name-prefix "${CLUSTER}-dns" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size "Standard_D8S_v4" \\
  --max-pods 250 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --enable-managed-identity \\
  --generate-ssh-keys
"""

uploadResultScript = """
az storage blob upload \\
  --account-name "${RESULT_STORAGE_ACCOUNT}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --container-name "${RESULT_CONTAINER}" \\
  --name "$(RUN_ID)/run-result.json" \\
  --file /tmp/run-result.json \\
  --auth-mode login \\
  --overwrite
"""

output = ap.Pipeline {
    name = "Image Pull Load"
    trigger = ["v2"]
    pool = POOL
    jobs = [
        job.Job {
            job = "imagePullLoad"
            displayName = "Image Pull Load"
            timeoutInMinutes = 1440
            steps = [
                common.SetRunId()
                common.InstallPythonDependencies()
                azure.Login(SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION)
                azure.CreateResourceGroup(SERVICE_CONNECTION, RESOURCE_GROUP, LOCATION, SUBSCRIPTION_ID)
                azure.AzCli(SERVICE_CONNECTION, "Create cluster", createClusterScript)
                *[azure.CreateNodePool(SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID, azure.NodePool {
                    name = p.name
                    sku = p.sku
                    count = p.count
                    taintPrefix = PULL_POOL_TAINT_PREFIX
                    labels = PULL_POOL_LABEL
                }) for p in azure.PlanNodePools({PULL_POOL_SKU: PULL_POOL_NODE_COUNT}, MAX_NODES_PER_POOL)]
                azure.GetCredentials(SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID)
                k8s.RunImagePullLoad(SERVICE_CONNECTION, PULL_NAMESPACE, manifest="kcl/image_pull_load/image-pull-load.yaml", durationSeconds=LOAD_DURATION_SECONDS, images=PULL_IMAGE)
                k8s.CollectImagePullThroughput(SERVICE_CONNECTION, PULL_NAMESPACE, manifest="kcl/image_pull_load/image-pull-load.yaml", region=LOCATION, nodeCount=PULL_POOL_NODE_COUNT, durationSeconds=LOAD_DURATION_SECONDS)
                azure.AzCli(SERVICE_CONNECTION, "Upload result to storage account", uploadResultScript)
                azure.DeleteResourceGroup(SERVICE_CONNECTION, RESOURCE_GROUP, SUBSCRIPTION_ID)
            ]
        }
    ]
}
