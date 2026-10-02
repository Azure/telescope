import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.steps.azure
import lib.steps.common
import lib.steps.health
import lib.util.asi_dashboard

# Pipeline variables, set when the pipeline is registered. Set
# NODE_STARTUP_SUBSCRIPTION_ID to the benchmark subscription, and
# NODE_STARTUP_SERVICE_CONNECTION to a service connection with Contributor on it. Because
# the connection is referenced through a variable, authorize it for this pipeline in
# advance (service connection > Security > Pipeline permissions).
SUBSCRIPTION_ID = "$(NODE_STARTUP_SUBSCRIPTION_ID)"
SERVICE_CONNECTION = "$(NODE_STARTUP_SERVICE_CONNECTION)"
RESOURCE_GROUP = "$(RUN_ID)"
# australiaeast matches Telescope's AKS Automatic runs. v1 used eastus2euap and
# Standard_D8s_v3, but DSv3 is over quota there in SUBSCRIPTION_ID. The Ddsv5
# quota (100 vCPU) fits one stage (at most 11 nodes = 44 vCPU); running more
# stages in parallel needs the requested increase.
LOCATION = "australiaeast"
NODE_SKU = "Standard_D4ds_v5"
CLUSTER = "nsl-cilium"
KUBECONFIG = "$(Pipeline.Workspace)/kubeconfig"
TARGET_POOL = "userpool"
DEFAULT_ITERATIONS = 5
# v1 value: gives Cluster Autoscaler time to leave backoff between scale-ups.
DEFAULT_CLUSTER_AUTOSCALER_COOLDOWN_SECONDS = 240
# ADO compile-time expression: whether a run uses the checked-in defaults. Built by
# concatenation because KCL can't interpolate values inside a "${{ }}" expression.
USES_DEFAULT_SETTINGS = "$" + "{{ and(eq(parameters.iterations, " + str(DEFAULT_ITERATIONS) \
    + "), eq(parameters.cluster_autoscaler_cooldown_seconds, " + str(DEFAULT_CLUSTER_AUTOSCALER_COOLDOWN_SECONDS) + ")) }}"
# The measurement stops starting new iterations CLEANUP_RESERVE_MINUTES before the
# job timeout, so everything after it still fits: an iteration started just before
# that point can take ~27 min (10 min step timeout + up to 15 min of autoscaler
# deadline extensions + event lookup and collection), then printing results, the
# ASI step and the synchronous resource group delete (~10 min).
JOB_TIMEOUT_MINUTES = 240
CLEANUP_RESERVE_MINUTES = 45
# Lifecycle tags on the per-run resource group and cluster. The shell evaluates the
# dates when the step runs, so deletion_due_time is 3 days after creation. A safety
# net for leaked resources; DeleteResourceGroup (always()) is the normal cleanup.
LIFECYCLE_TAGS = "owner=carvela creation_time=$(date -u +%Y-%m-%dT%H:%M:%SZ) deletion_due_time=$(date -u -d '+3 days' +%Y-%m-%dT%H:%M:%SZ)"

output = ap.Pipeline {
    name = "Node Startup Latency"
    # Manual and scheduled runs only. CI and PR triggers would need GitHub webhook
    # admin rights on Azure/telescope when the pipeline is registered.
    trigger = "none"
    pr = "none"
    # Microsoft-hosted agent. ubuntu-22.04 ships Python 3.10, az, kubectl and jq, which
    # the steps use, and still allows the plain `pip3 install` in InstallPythonDependencies
    # (Ubuntu 24.04 images reject it with an externally-managed-environment error).
    pool = {vmImage = "ubuntu-22.04"}
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
        ap.Stage {
            stage = "managed_cilium"
            displayName = "Azure CNI Overlay with managed Cilium"
            # Scenarios are independent: a failure in one must not skip the others,
            # and each stage can be run alone via "Stages to run".
            dependsOn = []
            jobs = [job.Job {
                job = "node_startup_latency"
                displayName = "Measure autoscaled node startup latency"
                timeoutInMinutes = JOB_TIMEOUT_MINUTES
                # Exposed to every step, so kubectl (health check) and the measurement
                # both use this cluster's credentials.
                variables = {
                    KUBECONFIG = KUBECONFIG
                }
                steps = [
                    common.RecordCurrentTime("JOB_START_TIME"),
                    common.SetRunId(),
                    common.InstallPythonDependencies(),
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
                    azure.AzCli(
                        SERVICE_CONNECTION,
                        "Create AKS cluster",
                        """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --tier standard \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --network-dataplane cilium \\
  --service-cidr 192.168.0.0/16 \\
  --dns-service-ip 192.168.0.10 \\
  --nodepool-name default \\
  --node-count 1 \\
  --node-vm-size "${NODE_SKU}" \\
  --node-osdisk-type Ephemeral \\
  --nodepool-taints "CriticalAddonsOnly=true:NoSchedule" \\
  --tags SkipAKSCluster=true SkipASMAzSecPackAutoConfig=true SkipLinuxAzSecPack=true ${LIFECYCLE_TAGS}
"""),
                    azure.CreateNodePool(
                        SERVICE_CONNECTION,
                        CLUSTER,
                        RESOURCE_GROUP,
                        SUBSCRIPTION_ID,
                        azure.NodePool {
                            name = TARGET_POOL
                            sku = NODE_SKU
                            count = 1
                            minCount = 1
                            maxCount = 10
                            osDiskType = "Ephemeral"
                            labels = "node-startup-latency=true"
                        }),
                    azure.GetCredentials(
                        SERVICE_CONNECTION,
                        CLUSTER,
                        RESOURCE_GROUP,
                        SUBSCRIPTION_ID,
                        KUBECONFIG),
                    health.ValidateWorkloadHealth(
                        SERVICE_CONNECTION,
                        "daemonset",
                        "cilium",
                        "kube-system"),
                    # Default customer clusters have no Defender sensor; an extra DaemonSet
                    # starting on every new node would skew startup times.
                    azure.AzCli(
                        SERVICE_CONNECTION,
                        "Check Defender sensor is off",
                        """
defender=$(az aks show \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --query "securityProfile.defender.securityMonitoring.enabled" \\
  --output tsv)
if [ "$defender" = "true" ]; then
  echo "FAILED ENVIRONMENT CHECK: Defender sensor is enabled on the cluster"
  exit 1
fi
"""),
                    common.RecordCurrentTime("BENCHMARK_START_TIME"),
                    azure.AzCli(
                        SERVICE_CONNECTION,
                        "Measure node startup latency",
                        """
az aks show \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --output json > /tmp/aks-cluster.json

deadline=$(( $(date -u -d "$(JOB_START_TIME)" +%s) + (${JOB_TIMEOUT_MINUTES} - ${CLEANUP_RESERVE_MINUTES}) * 60 ))

cd "$(Pipeline.Workspace)/s/modules/python"
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 node_startup/main.py \\
  --scenario managed-cilium \\
  --provisioner cluster-autoscaler \\
  --cluster-info-file /tmp/aks-cluster.json \\
  --node-pool-name "${TARGET_POOL}" \\
  --node-label-key agentpool \\
  --cni-daemonset-label k8s-app=cilium \\
  --cni-blocking-taint node.cilium.io/agent-not-ready \\
  --supplementary-cni-pod azure_cns=k8s-app=azure-cns \\
  --probe-namespace node-startup-latency \\
  --iterations \${{ parameters.iterations }} \\
  --iteration-cooldown-seconds \${{ parameters.cluster_autoscaler_cooldown_seconds }} \\
  --step-timeout-seconds 600 \\
  --deadline-epoch-seconds "$deadline" \\
  --uses-default-settings ${USES_DEFAULT_SETTINGS} \\
  --records-file /tmp/node-startup-records.jsonl

# One JSON line per valid iteration, in the envelope Telescope result storage expects.
# Results are only printed to the log. Uploading is intentionally disabled.
# TODO: add common.UploadResult once the results storage and Kusto ingestion exist.
jq -c '{
  timestamp: .operation.end_timestamp,
  run_id: "$(RUN_ID)",
  run_url: "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)",
  pipeline: "$(Build.DefinitionName)",
  result: .
}' /tmp/node-startup-records.jsonl > /tmp/run-result.json
cat /tmp/run-result.json
"""),
                    common.RecordCurrentTime("BENCHMARK_END_TIME"),
                    asi_dashboard.PrintAsiDashboardUrl(
                        SERVICE_CONNECTION,
                        CLUSTER,
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
        },
    ]
}
