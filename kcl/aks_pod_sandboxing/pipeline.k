import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common

SUBSCRIPTION_ID = const.DEFAULT_SUBSCRIPTION_ID
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "uksouth"
CLUSTER = "kata-pod-startup"
K8S_VERSION = "1.35"
KATA_POOL_NAME = "katapool"
KATA_NODE_SKU = "Standard_D4s_v3"
POD_NAME = "pause-sandbox"
RUNTIME_CLASS = "kata-vm-isolation"
PAUSE_IMAGE = "mcr.microsoft.com/oss/kubernetes/pause:3.6"

createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "${K8S_VERSION}" \\
  --os-sku AzureLinux \\
  --node-count 1 \\
  --node-vm-size Standard_D2s_v3 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --tier standard \\
  --tags SkipAKSCluster=true SkipASMAzSecPackAutoConfig=true SkipLinuxAzSecPack=true
"""

addKataPoolScript = """
az aks nodepool add \\
  --cluster-name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --name "${KATA_POOL_NAME}" \\
  --node-count 1 \\
  --node-vm-size "${KATA_NODE_SKU}" \\
  --os-sku AzureLinux \\
  --workload-runtime KataVmIsolation \\
  --mode User

az aks update \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --yes
"""

scheduleAndMeasureScript = """
export KUBECONFIG="$(Pipeline.Workspace)/kubeconfig"

cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
spec:
  runtimeClassName: ${RUNTIME_CLASS}
  containers:
    - name: pause
      image: ${PAUSE_IMAGE}
EOF

kubectl wait --for=condition=Ready pod/${POD_NAME} --timeout=10m

pod_json=$(kubectl get pod ${POD_NAME} -o json)
events_json=$(kubectl get events --field-selector involvedObject.name=${POD_NAME} -o json)

python3 - "$pod_json" "$events_json" <<'PY'
import json, sys, datetime

pod = json.loads(sys.argv[1])
events = json.loads(sys.argv[2])

def parse(ts):
    if not ts:
        return None
    ts = ts.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(ts)

def event_time(reason):
    for e in events.get("items", []):
        if e.get("reason") == reason:
            return e.get("firstTimestamp") or e.get("eventTime")
    return None

scheduled = event_time("Scheduled")
pulling = event_time("Pulling")
pulled = event_time("Pulled")
created = event_time("Created")
started = event_time("Started")

ready = None
for c in pod.get("status", {}).get("conditions", []):
    if c.get("type") == "Ready" and c.get("status") == "True":
        ready = c.get("lastTransitionTime")
        break

startup_latency = None
if scheduled and ready:
    startup_latency = (parse(ready) - parse(scheduled)).total_seconds()

import os
result = {
    "run_id": os.environ.get("RUN_ID", ""),
    "cluster": "${CLUSTER}",
    "runtime_class": "${RUNTIME_CLASS}",
    "node_sku": "${KATA_NODE_SKU}",
    "k8s_version": "${K8S_VERSION}",
    "pod_name": "${POD_NAME}",
    "image": "${PAUSE_IMAGE}",
    "scheduled_time": scheduled,
    "pulling_time": pulling,
    "pulled_time": pulled,
    "created_time": created,
    "started_time": started,
    "ready_time": ready,
    "startup_latency_seconds": startup_latency,
}

with open("/tmp/run-result.json", "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))

if startup_latency is None or startup_latency <= 0:
    raise SystemExit("Startup latency could not be computed")
PY
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
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create AKS cluster",
                    createClusterScript),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Add Kata VM-isolation node pool",
                    addKataPoolScript),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "$(Pipeline.Workspace)/kubeconfig"),
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
                    SUBSCRIPTION_ID),
            ]
        }]
    }]
}
