import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.kperf

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
# TODO: Replace the user-selected PR image with a published upstream release.
RUNNER_IMAGE = "ghcr.io/liyu-ma/kperf@sha256:36f8e1cdbb6a4bd2fde4b29bf0cb5e4e014484ae9ddca9136f43449897ffb647"
CREATE_NEW_CLUSTER = "and(succeeded(), eq(variables['USE_EXISTING_CLUSTER'], 'false'))"
RATES = [50, 100, 200]

output = ap.Pipeline {
    name = "Workload Identity Webhook Benchmark"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "existing_resource_group"
            displayName = "Existing resource group (none creates a cluster)"
            type = "string"
            default = "none"
        },
        ap.Parameter {
            name = "existing_cluster"
            displayName = "Existing cluster name (provide together with resource group)"
            type = "string"
            default = "none"
        },
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark (phase Pods are deleted)"
            type = "boolean"
            default = False
        },
    ]
    jobs = [
        job.Job {
            job = "benchmark"
            displayName = "Run WI webhook traffic on a new or existing cluster"
            timeoutInMinutes = 240
            # Allow an active phase's bounded cleanup and five-minute recovery pause.
            cancelTimeoutInMinutes = 25
            variables = {
                RUN_ID = "wi-$(Build.BuildId)-$(System.JobAttempt)"
                RESOURCE_GROUP_CREATED = "false"
                USE_EXISTING_CLUSTER = "unresolved"
                KUBECONFIG = "$(Agent.TempDirectory)/$(RUN_ID).kubeconfig"
                **{"PHASE_${rate}_STARTED" = "false" for rate in RATES}
            }
            steps = [
                steps.Bash {
                    bash = """
set -euo pipefail
resource_group="$PARAM_EXISTING_RESOURCE_GROUP"
cluster="$PARAM_EXISTING_CLUSTER"
if [ "$resource_group" = "none" ]; then resource_group=""; fi
if [ "$cluster" = "none" ]; then cluster=""; fi
if { [ -z "$resource_group" ] && [ -n "$cluster" ]; } ||
   { [ -n "$resource_group" ] && [ -z "$cluster" ]; }; then
  echo "existing_resource_group and existing_cluster must be provided together." >&2
  exit 1
fi
if [ -n "$cluster" ]; then
  use_existing=true
else
  use_existing=false
  resource_group="$RUN_ID"
  cluster=wi-webhook
fi
# Reused resource groups also name the existing Kubernetes namespace.
if ! [[ "$resource_group" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] ||
   [ "\${#resource_group}" -gt 63 ]; then
  echo "The resource group must also be a valid Kubernetes namespace (lowercase DNS label, at most 63 characters)." >&2
  exit 1
fi
if ! [[ "$cluster" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] ||
   [ "\${#cluster}" -gt 63 ]; then
  echo "Invalid existing cluster name." >&2
  exit 1
fi
echo "Benchmark target: cluster=$cluster resource_group=$resource_group namespace=$resource_group existing=$use_existing"
echo "##vso[task.setvariable variable=RESOURCE_GROUP]$resource_group"
echo "##vso[task.setvariable variable=CLUSTER]$cluster"
echo "##vso[task.setvariable variable=BENCHMARK_NAMESPACE]$resource_group"
echo "##vso[task.setvariable variable=USE_EXISTING_CLUSTER]$use_existing"
"""
                    displayName = "Resolve benchmark cluster"
                    env = {
                        PARAM_EXISTING_RESOURCE_GROUP = "\${{ parameters.existing_resource_group }}"
                        PARAM_EXISTING_CLUSTER = "\${{ parameters.existing_cluster }}"
                    }
                },
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Verify resource group does not already exist",
                    """
exists=$(az group exists --subscription "${SUBSCRIPTION_ID}" --name "$(RESOURCE_GROUP)")
if [ "$exists" != "false" ]; then
  echo "Refusing to reuse an existing or unverified resource group: $(RESOURCE_GROUP)" >&2
  exit 1
fi
""",
                    condition=CREATE_NEW_CLUSTER),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RESOURCE_GROUP)",
                    LOCATION,
                    SUBSCRIPTION_ID,
                    condition=CREATE_NEW_CLUSTER),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create H2 cluster with OIDC and workload identity",
                    """
echo "##vso[task.setvariable variable=RESOURCE_GROUP_CREATED]true"
az extension add \\
  --name aks-preview \\
  --version 20.0.0b6 \\
  --allow-preview true \\
  --yes
az aks create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(RESOURCE_GROUP)" \\
  --name "$(CLUSTER)" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --dns-name-prefix "$(RUN_ID)" \\
  --tier standard \\
  --control-plane-scaling-size H2 \\
  --enable-oidc-issuer \\
  --enable-workload-identity \\
  --enable-azure-monitor-metrics \\
  --azure-monitor-workspace-resource-id "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/wi-benchmark-monitoring/providers/Microsoft.Monitor/accounts/wi-benchmark-prometheus" \\
  --generate-ssh-keys \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size Standard_D4_v4 \\
  --max-pods 50 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --tags SkipAKSCluster=true \\
  --yes
""",
                    condition=CREATE_NEW_CLUSTER),
                steps.Task {
                    **azure.CreateNodePool(
                        const.DEFAULT_SERVICE_CONNECTION,
                        "$(CLUSTER)",
                        "$(RESOURCE_GROUP)",
                        SUBSCRIPTION_ID,
                        azure.NodePool {
                            name = "workerpool"
                            sku = "Standard_D2s_v5"
                            count = 3
                        })
                    condition = CREATE_NEW_CLUSTER
                },
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(CLUSTER)",
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    file="$(KUBECONFIG)"),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Prepare WI resources",
                    """
set -u
kubectl create namespace "$(BENCHMARK_NAMESPACE)" --dry-run=client -o yaml | kubectl apply -f -
kubectl create serviceaccount pod-benchmark --namespace "$(BENCHMARK_NAMESPACE)" --dry-run=client -o yaml | kubectl apply -f -
# Use a fake client ID because benchmark Pods do not access Azure resources.
kubectl annotate serviceaccount pod-benchmark \\
  --namespace "$(BENCHMARK_NAMESPACE)" \\
  "azure.workload.identity/client-id=00000000-0000-4000-8000-000000000001" \\
  --overwrite
"""),
                kperf.InstallRunkperf(RUNNER_IMAGE),
                *[step for rate in RATES for step in [
                    steps.Bash {
                        bash = """
set -euo pipefail
profile="$(Agent.TempDirectory)/$(RUN_ID)-r${rate}-load-profile.yaml"
sed \\
  -e 's/__RUN_NAMESPACE__/$(BENCHMARK_NAMESPACE)/g' \\
  -e 's/__RATE__/${rate}/g' \\
  -e 's/__PHASE_RUN_ID__/$(RUN_ID)-r${rate}/g' \\
  "$(Build.SourcesDirectory)/kcl/workload_identity_webhook/load-profile.yaml" > "$profile"
if grep -q '__[A-Z_]*__' "$profile"; then
  echo "Unresolved load-profile placeholders" >&2
  exit 1
fi
echo "Starting ${rate} CREATEs/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ); ownership=$(RUN_ID)-r${rate}"
echo "##vso[task.setvariable variable=PHASE_${rate}_STARTED]true"
"""
                        displayName = "Prepare ${rate}/sec load profile"
                    },
                    kperf.RunKperfRunner(
                        profilePath="$(Agent.TempDirectory)/$(RUN_ID)-r${rate}-load-profile.yaml",
                        kubeconfig="$(KUBECONFIG)") | {
                            displayName = "Run kperf at ${rate} CREATEs/sec"
                            timeoutInMinutes = 15
                        },
                    steps.Bash {
                        bash = """
set -euo pipefail
echo "Cleaning ${rate}/sec phase Pods at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
kubectl --request-timeout=60s delete pods \\
  --namespace "$(BENCHMARK_NAMESPACE)" \\
  --selector "benchmark-run=$(RUN_ID)-r${rate}" \\
  --wait=true \\
  --timeout=10m
echo "Finished ${rate}/sec phase cleanup at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
                        displayName = "Delete ${rate}/sec phase Pods"
                        condition = "and(always(), eq(variables['PHASE_${rate}_STARTED'], 'true'))"
                        timeoutInMinutes = 15
                    },
                    steps.Bash {
                        bash = """
set -euo pipefail
echo "Starting five-minute pause after ${rate}/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
sleep 300
echo "Finished pause after ${rate}/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
                        displayName = "Pause 5 minutes after ${rate}/sec"
                        condition = "and(always(), eq(variables['PHASE_${rate}_STARTED'], 'true'))"
                        timeoutInMinutes = 6
                    },
                ]],
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    condition="and(always(), eq(variables['USE_EXISTING_CLUSTER'], 'false'), eq(variables['RESOURCE_GROUP_CREATED'], 'true'), not(\${{ parameters.keep_cluster }}))"),
            ]
        },
    ]
}
