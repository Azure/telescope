import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common

RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "uksouth"
CLUSTER = "kata-pod-startup"
K8S_VERSION = "1.36"
NODE_SKU = "Standard_D4s_v3"
POD_NAME = "pause-sandbox"
RUNTIME_CLASS = "kata-vm-isolation"
PAUSE_IMAGE = "mcr.microsoft.com/oss/kubernetes/pause:3.6"

createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "${K8S_VERSION}" \\
  --os-sku AzureLinux \\
  --workload-runtime KataVmIsolation \\
  --node-count 3 \\
  --node-vm-size ${NODE_SKU} \\
  --network-plugin azure \\
  --tier standard
"""

scheduleAndMeasureScript = """
export KUBECONFIG="$(Pipeline.Workspace)/kubeconfig"
export POD_NAME="${POD_NAME}"
export CLUSTER="${CLUSTER}"
export RUNTIME_CLASS="${RUNTIME_CLASS}"
export NODE_SKU="${NODE_SKU}"
export K8S_VERSION="${K8S_VERSION}"
export PAUSE_IMAGE="${PAUSE_IMAGE}"

MANIFEST="$(Pipeline.Workspace)/pod.yaml"

kcl run "$(Build.SourcesDirectory)/kcl/aks_pod_sandboxing/pod.k" \\
  -D podName="${POD_NAME}" \\
  -D runtimeClass="${RUNTIME_CLASS}" \\
  -D image="${PAUSE_IMAGE}" \\
  -o "$MANIFEST"

kubectl apply -f "$MANIFEST"
kubectl wait --for=condition=Ready pod/${POD_NAME} --timeout=10m
python3 "$(Build.SourcesDirectory)/kcl/aks_pod_sandboxing/measure.py"
"""

output = ap.Pipeline {
    name = "AKS Pod Sandboxing Pod Startup"
    pool = const.DEFAULT_POOL
    stages = [ap.Stage {
        stage = "measure"
        displayName = "Kata Pod Startup"
        jobs = [job.Job {
            job = "measure_pod_startup"
            displayName = "Measure pause pod startup with Kata sandboxing"
            timeoutInMinutes = 90
            steps = [
                common.SetRunId(),
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
                    "Create AKS cluster",
                    createClusterScript),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID,
                    "$(Pipeline.Workspace)/kubeconfig"),
                common.InstallKcl(),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Schedule pause pod and measure startup",
                    scheduleAndMeasureScript),
                common.UploadResult(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "telescopev2",
                    "137f0351-8235-42a6-ac7a-6b46be2d21c7",
                    "aks"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    const.DEFAULT_SUBSCRIPTION_ID),
            ]
        }]
    }]
}
