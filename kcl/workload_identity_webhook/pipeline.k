import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.kperf
import lib.util.asi_dashboard

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
# TODO: Replace the user-selected PR image with a published upstream release.
RUNNER_IMAGE = "ghcr.io/liyu-ma/kperf@sha256:36f8e1cdbb6a4bd2fde4b29bf0cb5e4e014484ae9ddca9136f43449897ffb647"
POD_CREATE_RPS = [50, 100, 150]

BenchmarkSteps = lambda rate: int -> [steps.Step] {
    [
        steps.Bash {
            bash = """
set -euo pipefail
namespace="$(RUN_ID)-r${rate}"
deleting=$(kubectl --request-timeout=60s get namespace "$namespace" --ignore-not-found -o jsonpath='{.metadata.deletionTimestamp}')
if [ -n "$deleting" ]; then
  echo "Namespace $namespace is already terminating; cannot prepare this phase." >&2
  exit 1
fi
kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl --request-timeout=60s apply -f -
kubectl create serviceaccount pod-benchmark --namespace "$namespace" --dry-run=client -o yaml | kubectl --request-timeout=60s apply -f -
# Use a fake client ID because benchmark Pods do not access Azure resources.
kubectl --request-timeout=60s annotate serviceaccount pod-benchmark \\
  --namespace "$namespace" \\
  "azure.workload.identity/client-id=00000000-0000-4000-8000-000000000001" \\
  --overwrite
"""
            displayName = "Prepare WI resources for ${rate}/sec"
        },
        steps.Bash {
            bash = """
set -euo pipefail
profile="$(Agent.TempDirectory)/$(RUN_ID)-r${rate}-load-profile.yaml"
sed \\
  -e 's/__RUN_NAMESPACE__/$(RUN_ID)-r${rate}/g' \\
  -e 's/__RATE__/${rate}/g' \\
  -e 's/__PHASE_RUN_ID__/$(RUN_ID)-r${rate}/g' \\
  "$(Build.SourcesDirectory)/kcl/workload_identity_webhook/load-profile.yaml" > "$profile"
if grep -q '__[A-Z_]*__' "$profile"; then
  echo "Unresolved load-profile placeholders" >&2
  exit 1
fi
"""
            displayName = "Prepare ${rate}/sec load profile"
        },
        steps.Script {
            script = """
set -euo pipefail
set -x

kperf runner run \\
  --config "$(Agent.TempDirectory)/$(RUN_ID)-r${rate}-load-profile.yaml" \\
  --kubeconfig "$(KUBECONFIG)"
"""
            displayName = "Run kperf at ${rate} CREATEs/sec"
            timeoutInMinutes = 15
        },
        steps.Bash {
            bash = """
set -euo pipefail
if [ ! -s "$(KUBECONFIG)" ]; then
  echo "Skipping namespace deletion for ${rate}/sec: kubeconfig is missing or empty: $(KUBECONFIG)"
  exit 0
fi
kubectl --request-timeout=60s delete namespace "$(RUN_ID)-r${rate}" \\
  --ignore-not-found=true \\
  --wait=true \\
  --timeout=10m
echo "Namespace cleanup completed for ${rate}/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
            displayName = "Delete namespace from ${rate}/sec run"
            condition = "always()"
            continueOnError = True
            timeoutInMinutes = 15
        },
        steps.Bash {
            bash = """
set -euo pipefail
echo "Starting five-minute pause after ${rate}/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
sleep 300
echo "Finished pause after ${rate}/sec phase at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
            displayName = "Pause 5 minutes after kperf run"
            condition = "always()"
            timeoutInMinutes = 6
        },
    ]
}

output = ap.Pipeline {
    name = "Workload Identity Webhook Benchmark"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark (phase namespaces are deleted)"
            type = "boolean"
            default = False
        },
    ]
    jobs = [
        job.Job {
            job = "benchmark"
            displayName = "Baseline Run: 50/100/150 RPS"
            timeoutInMinutes = 240
            # Allow bounded cleanup and recovery during cancellation.
            cancelTimeoutInMinutes = 25
            variables = {
                RUN_ID = "wi-$(Build.BuildId)-$(System.JobAttempt)"
                RESOURCE_GROUP = "$(RUN_ID)"
                CLUSTER = "wi-webhook"
                KUBECONFIG = "$(Agent.TempDirectory)/$(RUN_ID).kubeconfig"
            }
            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RESOURCE_GROUP)",
                    LOCATION,
                    SUBSCRIPTION_ID),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create H2 cluster with OIDC and workload identity",
                    """
az extension add \\
  --name aks-preview \\
  --version 21.0.0b17 \\
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
"""),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(CLUSTER)",
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    file="$(KUBECONFIG)"),
                kperf.InstallRunkperf(RUNNER_IMAGE),
                common.RecordCurrentTime("BENCHMARK_START_TIME"),
                *[step for rate in POD_CREATE_RPS for step in BenchmarkSteps(rate)],
                asi_dashboard.PrintAsiDashboardUrl(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(CLUSTER)",
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    startTime="$(BENCHMARK_START_TIME)"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    condition="and(always(), not(\${{ parameters.keep_cluster }}))"),
            ]
        },
    ]
}
