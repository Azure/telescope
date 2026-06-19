import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

# End-to-end example: stand up an AKS cluster with a dedicated image-pull node
# pool, then drive sustained registry blob-download traffic against an ACR stamp's
# data proxy for a fixed duration using the RunImagePullLoad step (one puller per
# node running concurrent OCI blob GETs). See kcl/image_pull_load/image-pull-load.yaml
# for the load generator and lib/steps/k8s/run_image_pull_load.k for the step.
# ACR-team-specific values (overriding the Telescope const.k defaults).
# "ACR - Dev" service connection targets subscription dfb63c8c.
SERVICE_CONNECTION = "ACR - Dev"
POOL = "Default"
SUBSCRIPTION_ID = "dfb63c8c-7c89-4ef8-af13-75c1d873c895"
RESOURCE_GROUP = "$(RUN_ID)"

# Queue-time pipeline parameter (see `parameters` below). The escaped
# ${{ parameters.location }} is emitted verbatim for ADO to resolve at compile time.
LOCATION = "\${{ parameters.location }}"
CLUSTER = "image-pull-load"

# Dedicated pool the pullers run on. The label/taint match the DaemonSet's
# nodeSelector + tolerations in image-pull-load.yaml.
PULL_POOL_LABEL = "cri-resource-consume=true"
PULL_POOL_TAINT_PREFIX = "cri-resource-consume"
PULL_POOL_SKU = "Standard_D4s_v3"
PULL_POOL_NAME = "workerpool0"

# A single AKS user node pool supports at most this many nodes. The validate step
# fails the run if node_count exceeds it.
MAX_NODE_COUNT = 1000

# Concurrency dial: queue-time pipeline parameter (see `parameters` below). One
# puller pod runs per node, so node count == puller count; all pullers run on a
# single dedicated node pool. NOTE: ensure regional vCPU quota covers
# node_count * SKU cores (e.g. 1000 x Standard_D4s_v3 = 4000 vCPUs).
PULL_POOL_NODE_COUNT = "\${{ parameters.node_count }}"

# Concurrent blob-download loops per puller pod. Total in-flight streams across
# the fleet = node_count * concurrency. Queue-time pipeline parameter.
CONCURRENCY = "\${{ parameters.concurrency }}"

PULL_NAMESPACE = "image-pull-load"

# Duration and image under test are queue-time pipeline parameters (see
# `parameters` below); the escaped ${{ parameters.X }} is emitted verbatim for
# ADO to resolve at compile time.
LOAD_DURATION_SECONDS = "\${{ parameters.load_duration_seconds }}"
PULL_IMAGE = "\${{ parameters.pull_image }}"

# Result storage (ACR-team self-hosted Telescope v2 data infra, same sub as the
# service connection). The run-result.json is ingested into the ADX `results`
# table via Event Grid -> Event Hub. Shared-key auth is disabled by policy, so we
# upload with --auth-mode login; the service connection identity must hold the
# Storage Blob Data Contributor role on this account.
RESULT_STORAGE_ACCOUNT = "acrtelescoperesults"
RESULT_CONTAINER = "acr"

# Fail the run fast (before creating any Azure resources) if the requested
# node_count exceeds the single-pool maximum.
validateNodeCountScript = """
set -euo pipefail
node_count=${PULL_POOL_NODE_COUNT}
if [ "$node_count" -gt ${MAX_NODE_COUNT} ]; then
  echo "ERROR: node_count=$node_count exceeds the maximum of ${MAX_NODE_COUNT} (single AKS node pool cap)." >&2
  exit 1
fi
echo "node_count=$node_count is within the limit (max ${MAX_NODE_COUNT})."
"""

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

# Single dedicated puller node pool sized by the node_count parameter. Mirrors
# azure.CreateNodePool's transient-error retry (AKS can return OperationNotAllowed
# while a background addon op runs) but takes the runtime node count, which the
# compile-time NodePool schema can't carry.
createPullPoolScript = """
deadline=$(($(date +%s) + 600))
sleep_between=30
attempt=0
while :; do
  attempt=$((attempt + 1))
  set +e
  output=$(az aks nodepool add \\
    --cluster-name "${CLUSTER}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --name "${PULL_POOL_NAME}" \\
    --node-count ${PULL_POOL_NODE_COUNT} \\
    --node-vm-size "${PULL_POOL_SKU}" \\
    --mode User \\
    --node-taints ${PULL_POOL_TAINT_PREFIX}=true:NoSchedule \\
    --labels "${PULL_POOL_LABEL}" 2>&1)
  rc=$?
  set -e
  echo "$output"
  if [ $rc -eq 0 ]; then
    exit 0
  fi
  if echo "$output" | grep -qiE "OperationNotAllowed"; then
    now=$(date +%s)
    if [ $now -ge $deadline ]; then
      echo "Retriable error persisted past retry window ($attempt attempts); giving up."
      exit $rc
    fi
    remaining=$((deadline - now))
    echo "Attempt $attempt matched retriable pattern; retrying in $sleep_between seconds ($remaining seconds remain)."
    sleep $sleep_between
  else
    echo "Non-retriable error (rc=$rc); giving up after attempt $attempt."
    exit $rc
  fi
done
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
    parameters = [
        ap.Parameter {
            name = "location"
            displayName = "Azure region for the AKS cluster + load"
            type = "string"
            default = "australiaeast"
        }
        ap.Parameter {
            name = "pull_image"
            displayName = "Image(s) under test (space-separated, fully-qualified refs)"
            type = "string"
            default = "acrstampperftest.azurecr-test.io/test_10gb_4l_v1:latest"
        }
        ap.Parameter {
            name = "load_duration_seconds"
            displayName = "Load duration (seconds)"
            type = "number"
            default = 1800
        }
        ap.Parameter {
            name = "node_count"
            displayName = "Puller node count (one pod per node; max 1000)"
            type = "number"
            default = 1000
        }
        ap.Parameter {
            name = "concurrency"
            displayName = "Concurrent blob-download loops per puller pod"
            type = "number"
            default = 4
        }
    ]
    jobs = [
        job.Job {
            job = "imagePullLoad"
            displayName = "Image Pull Load"
            timeoutInMinutes = 1440
            steps = [
                common.SetRunId()
                common.InstallPythonDependencies()
                steps.Script {
                    script = validateNodeCountScript
                    displayName = "Validate node_count <= ${MAX_NODE_COUNT}"
                }
                azure.Login(SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION)
                azure.CreateResourceGroup(SERVICE_CONNECTION, RESOURCE_GROUP, LOCATION, SUBSCRIPTION_ID)
                azure.AzCli(SERVICE_CONNECTION, "Create cluster", createClusterScript)
                azure.AzCli(SERVICE_CONNECTION, "Create node pool ${PULL_POOL_NAME}", createPullPoolScript)
                azure.GetCredentials(SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID)
                k8s.RunImagePullLoad(SERVICE_CONNECTION, PULL_NAMESPACE, manifest="kcl/image_pull_load/image-pull-load.yaml", durationSeconds=LOAD_DURATION_SECONDS, images=PULL_IMAGE, concurrency=CONCURRENCY)
                k8s.CollectImagePullThroughput(SERVICE_CONNECTION, PULL_NAMESPACE, manifest="kcl/image_pull_load/image-pull-load.yaml", region=LOCATION, nodeCount=PULL_POOL_NODE_COUNT, durationSeconds=LOAD_DURATION_SECONDS)
                azure.AzCli(SERVICE_CONNECTION, "Upload result to storage account", uploadResultScript)
                azure.DeleteResourceGroup(SERVICE_CONNECTION, RESOURCE_GROUP, SUBSCRIPTION_ID)
            ]
        }
    ]
}
