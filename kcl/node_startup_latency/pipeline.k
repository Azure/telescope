import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.health
import lib.util.asi_dashboard

# Pipeline variable, set where the pipeline is registered so the subscription isn't in
# the repo. It must have no Defender sensor and no policy that modifies default AKS
# clusters, so nodes match a default customer cluster, and SERVICE_CONNECTION needs
# Contributor on it.
SUBSCRIPTION_ID = "$(TELESCOPE_SUBSCRIPTION_ID)"
SERVICE_CONNECTION = const.DEFAULT_SERVICE_CONNECTION
RESOURCE_GROUP = "$(RUN_ID)"
# australiaeast matches Telescope's AKS Automatic runs. v1 used eastus2euap and
# Standard_D8s_v3, but DSv3 is over quota there in SUBSCRIPTION_ID. Each stage uses
# at most 11 Standard_D4ds_v5 nodes (44 vCPU), and the stages run in parallel, so
# the subscription's Ddsv5 quota (300 vCPU here) must cover 44 vCPU per stage.
LOCATION = "australiaeast"
TARGET_POOL = "userpool"
# Passed between steps: the measurement writes RECORDS_FILE, the format step turns it
# into RESULT_FILE, and UploadResult uploads RESULT_FILE.
RECORDS_FILE = "/tmp/node-startup-records.jsonl"
RESULT_FILE = "/tmp/run-result.json"
DEFAULT_ITERATIONS = 5
# v1 value: gives Cluster Autoscaler time to leave backoff between scale-ups.
DEFAULT_CLUSTER_AUTOSCALER_COOLDOWN_SECONDS = 240
# ADO compile-time expression: whether a run uses the checked-in defaults. Built by
# concatenation because KCL can't interpolate values inside a "${{ }}" expression.
USES_DEFAULT_SETTINGS = "$" + "{{ and(eq(parameters.iterations, " + str(DEFAULT_ITERATIONS) \
    + "), eq(parameters.cluster_autoscaler_cooldown_seconds, " + str(DEFAULT_CLUSTER_AUTOSCALER_COOLDOWN_SECONDS) + ")) }}"
# The measurement stops starting new iterations CLEANUP_RESERVE_MINUTES before the
# job timeout, so everything after it still fits: an iteration started just before
# that point can take ~32 min (30 min of fixed probe-wait phase timeouts + event
# lookup and collection), then printing results, the ASI step and the synchronous
# resource group delete (~10 min).
JOB_TIMEOUT_MINUTES = 240
CLEANUP_RESERVE_MINUTES = 45
# Lifecycle tags on the per-run resource group and cluster. The shell evaluates the
# dates when the step runs, so deletion_due_time is 3 days after creation. A safety
# net for leaked resources; DeleteResourceGroup (always()) is the normal cleanup.
LIFECYCLE_TAGS = "owner=carvela creation_time=$(date -u +%Y-%m-%dT%H:%M:%SZ) deletion_due_time=$(date -u -d '+3 days' +%Y-%m-%dT%H:%M:%SZ)"

# A CNI agent DaemonSet that must be ready on a new node before pods can be scheduled
# there; the measurement then uses its pod's readiness as the CNI readiness signal.
# Without one, the signal is the CNI config file being written (cni_conflist_placed).
schema CniAgent:
    daemonset: str
    label: str
    blockingTaint: str

# One scenario with the same cluster shape and measurement, scaled by Cluster Autoscaler.
# networkArgs are the "az aks create" network profile arguments that define the scenario.
# Without a cniAgent, the health check uses azure-cns, Azure CNI's IP management DaemonSet.
clusterAutoscalerStage = lambda {
    name: str,
    displayName: str,
    scenario: str,
    cluster: str,
    networkArgs: [str],
    cniAgent: CniAgent = None,
} -> ap.Stage {
    networkArgLines = "".join(["  ${arg} \\\n" for arg in networkArgs])
    cniAgentArgLines = "  --cni-daemonset-label ${cniAgent.label} \\\n  --cni-blocking-taint ${cniAgent.blockingTaint} \\\n" if cniAgent else ""
    ap.Stage {
        stage = name
        displayName = displayName
        # Scenarios are independent: a failure in one must not skip the others,
        # and each stage can be run alone via "Stages to run".
        dependsOn = []
        jobs = [job.Job {
            job = "node_startup_latency"
            displayName = "Measure autoscaled node startup latency"
            timeoutInMinutes = JOB_TIMEOUT_MINUTES
            steps = [
                common.RecordCurrentTime("JOB_START_TIME"),
                common.SetRunId(),
                common.InstallPythonDependencies(),
                steps.Task {
                    task = "KubeloginInstaller@0"
                    displayName = "Install kubelogin"
                },
                azure.Login(
                    SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.CreateResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    tags = LIFECYCLE_TAGS),
                # Entra ID (AAD) is required: Azure Policy CloudGov_KubernAuthN_AAD denies AKS
                # clusters without it. It only changes API server authentication, not how
                # nodes join the cluster.
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Create AKS cluster",
                    """
az aks create \\
  --name "${cluster}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --tier standard \\
  --enable-aad \\
  --enable-azure-rbac \\
${networkArgLines}  --service-cidr 192.168.0.0/16 \\
  --dns-service-ip 192.168.0.10 \\
  --nodepool-name default \\
  --node-count 1 \\
  --node-vm-size "Standard_D4ds_v5" \\
  --node-osdisk-type Ephemeral \\
  --nodepool-taints "CriticalAddonsOnly=true:NoSchedule" \\
  --tags SkipAKSCluster=true ${LIFECYCLE_TAGS}
"""),
                azure.CreateNodePool(
                    SERVICE_CONNECTION,
                    cluster,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    azure.NodePool {
                        name = TARGET_POOL
                        sku = "Standard_D4ds_v5"
                        count = 1
                        minCount = 1
                        maxCount = 10
                        osDiskType = "Ephemeral"
                        labels = "node-startup-latency=true"
                    }),
                azure.GetCredentials(
                    SERVICE_CONNECTION,
                    cluster,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                # SERVICE_CONNECTION needs Azure Kubernetes Service RBAC Cluster Admin on
                # SUBSCRIPTION_ID. Later kubectl and measurement steps must run as AzCli tasks
                # so kubelogin can get tokens from the Azure CLI login.
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Convert kubeconfig to Entra ID login",
                    "kubelogin convert-kubeconfig -l azurecli"),
                health.ValidateWorkloadHealth(
                    SERVICE_CONNECTION,
                    "daemonset",
                    cniAgent.daemonset if cniAgent else "azure-cns",
                    "kube-system"),
                # Default customer clusters have no Defender sensor; an extra DaemonSet
                # starting on every new node would skew startup times.
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Check Defender sensor is off",
                    """
defender=$(az aks show \\
  --name "${cluster}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --query "securityProfile.defender.securityMonitoring.enabled" \\
  --output tsv)
if [ "$defender" = "true" ]; then
  echo "FAILED ENVIRONMENT CHECK: Defender sensor is enabled on the cluster"
  exit 1
fi
"""),
                # An Azure Policy installs the AzSecPack add-on shortly after the node pool is
                # created. Its scale set updates conflict with Cluster Autoscaler's, so a scale-up
                # during the install fails and the autoscaler backs off for ~5 minutes (run 86026).
                # Wait for the install so the first iteration measures a normal scale-up. Never
                # fails the run: iterations that still hit a backoff are flagged in the result.
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Wait for AzSecPack add-on",
                    """
addon_url="https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${cluster}/extensionAddons/azuresecuritylinuxagent?api-version=2024-09-01"
start=$(date +%s)
while :; do
  state=$(az rest --method get --url "$addon_url" --query properties.provisioningState -o tsv 2>/dev/null || echo NotFound)
  elapsed=$(( $(date +%s) - start ))
  echo "AzSecPack add-on after $elapsed s: $state"
  case "$state" in
    Succeeded)
      exit 0 ;;
    Failed|Canceled)
      echo "##vso[task.logissue type=warning]AzSecPack add-on install ended as $state; continuing"
      exit 0 ;;
    NotFound)
      # Not created yet. If it never appears, the policy didn't install it on this cluster.
      if [ "$elapsed" -ge 300 ]; then
        echo "AzSecPack add-on not installed after $elapsed s; continuing"
        exit 0
      fi ;;
  esac
  if [ "$elapsed" -ge 600 ]; then
    echo "##vso[task.logissue type=warning]AzSecPack add-on still $state after $elapsed s; continuing"
    exit 0
  fi
  sleep 15
done
"""),
                common.RecordCurrentTime("BENCHMARK_START_TIME"),
                azure.AzCli(
                    SERVICE_CONNECTION,
                    "Measure node startup latency",
                    """
az aks show \\
  --name "${cluster}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --output json > /tmp/aks-cluster.json

deadline=$(( $(date -u -d "$(JOB_START_TIME)" +%s) + (${JOB_TIMEOUT_MINUTES} - ${CLEANUP_RESERVE_MINUTES}) * 60 ))

cd "$(Pipeline.Workspace)/s/modules/python"
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 node_startup/main.py \\
  --scenario ${scenario} \\
  --provisioner cluster-autoscaler \\
  --cluster-info-file /tmp/aks-cluster.json \\
  --node-pool-name "${TARGET_POOL}" \\
  --node-label-key agentpool \\
${cniAgentArgLines}  --supplementary-cni-pod azure_cns=k8s-app=azure-cns \\
  --probe-namespace node-startup-latency \\
  --iterations \${{ parameters.iterations }} \\
  --iteration-cooldown-seconds \${{ parameters.cluster_autoscaler_cooldown_seconds }} \\
  --deadline-epoch-seconds "$deadline" \\
  --uses-default-settings ${USES_DEFAULT_SETTINGS} \\
  --records-file "${RECORDS_FILE}"
"""),
                # One JSON line per valid iteration, in the envelope Telescope result storage
                # expects. Printed to the log, then uploaded by the next step.
                steps.Bash {
                    displayName = "Format results"
                    bash = """
set -exo pipefail
jq -c '{
  timestamp: .operation.end_timestamp,
  run_id: "$(RUN_ID)",
  run_url: "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)",
  pipeline: "$(Build.DefinitionName)",
  result: .
}' "${RECORDS_FILE}" > "${RESULT_FILE}"
cat "${RESULT_FILE}"
"""
                },
                # Telescope's shared results storage, ingested into Kusto by the Telescope
                # team. UploadResult uses storage account keys, so SERVICE_CONNECTION's
                # identity needs permission to list keys on that account. The default
                # condition (succeeded()) is also true for SucceededWithIssues, so a stage
                # with dropped iterations still uploads its valid ones; a stage with none
                # fails earlier and uploads nothing.
                common.UploadResult(
                    SERVICE_CONNECTION,
                    const.DEFAULT_STORAGE_ACCOUNT,
                    const.DEFAULT_STORAGE_SUBSCRIPTION_ID,
                    const.DEFAULT_STORAGE_CONTAINER,
                    localFile = RESULT_FILE),
                common.RecordCurrentTime("BENCHMARK_END_TIME"),
                asi_dashboard.PrintAsiDashboardUrl(
                    SERVICE_CONNECTION,
                    cluster,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "$(BENCHMARK_START_TIME)",
                    "$(BENCHMARK_END_TIME)"),
                azure.DeleteResourceGroup(
                    SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
            ]
        }]
    }
}

output = ap.Pipeline {
    name = "Node Startup Latency"
    # Scheduled and manual runs only: a run creates AKS clusters, so it shouldn't run on every push.
    trigger = "none"
    pr = "none"
    # Azure DevOps cron times are UTC: 04:00 Irish time in winter, 05:00 in summer (IST).
    schedules = [ap.Cron {
        cron = "0 4 * * *"
        displayName = "Daily 4AM UTC"
        branches = {include = ["v2"]}
        always = True
    }]
    pool = const.DEFAULT_POOL
    # Manual runs can override the checked-in defaults at queue time; the values
    # used are recorded in every result (result.config).
    parameters = [
        ap.Parameter {
            name = "iterations"
            displayName = "Iterations per scenario"
            type = "number"
            default = DEFAULT_ITERATIONS
        }
        ap.Parameter {
            name = "cluster_autoscaler_cooldown_seconds"
            displayName = "Cooldown between iterations, Cluster Autoscaler stages (seconds)"
            type = "number"
            default = DEFAULT_CLUSTER_AUTOSCALER_COOLDOWN_SECONDS
        }
    ]
    stages = [
        clusterAutoscalerStage(
            name = "managed_cilium",
            displayName = "Azure CNI Overlay with managed Cilium",
            scenario = "managed-cilium",
            cluster = "nsl-cilium",
            networkArgs = [
                "--network-plugin azure",
                "--network-plugin-mode overlay",
                "--network-dataplane cilium",
            ],
            cniAgent = CniAgent {
                daemonset = "cilium"
                label = "k8s-app=cilium"
                blockingTaint = "node.cilium.io/agent-not-ready"
            }),
        clusterAutoscalerStage(
            name = "azure_cni",
            displayName = "Azure CNI Overlay",
            scenario = "azure-cni",
            cluster = "nsl-azure-cni",
            networkArgs = [
                "--network-plugin azure",
                "--network-plugin-mode overlay",
            ]),
    ]
}
