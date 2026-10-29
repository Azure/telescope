import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.kperf

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
# TODO: Replace the user-selected PR image with a published upstream release.
RUNNER_IMAGE = "ghcr.io/liyu-ma/kperf@sha256:67e4924b23d2aea35526479721dd83f9afe707685a6efafd60916423017479d4"

output = ap.Pipeline {
    name = "Workload Identity Webhook Benchmark"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster and benchmark Pods after benchmark"
            type = "boolean"
            default = False
        },
    ]
    jobs = [
        job.Job {
            job = "benchmark"
            displayName = "Create H2 cluster and run WI webhook traffic"
            timeoutInMinutes = 240
            cancelTimeoutInMinutes = 10
            variables = {
                RUN_ID = "wi-$(Build.BuildId)-$(System.JobAttempt)"
                RESOURCE_GROUP_CREATED = "false"
                KUBECONFIG = "$(Agent.TempDirectory)/$(RUN_ID).kubeconfig"
                KPERF_PROFILE = "$(Agent.TempDirectory)/$(RUN_ID)-load-profile.yaml"
                KPERF_RESULT = "$(Agent.TempDirectory)/$(RUN_ID)-result.json"
            }
            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Verify resource group does not already exist",
                    """
exists=$(az group exists --subscription "${SUBSCRIPTION_ID}" --name "$(RUN_ID)")
if [ "$exists" != "false" ]; then
  echo "Refusing to reuse an existing or unverified resource group: $(RUN_ID)" >&2
  exit 1
fi
"""),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RUN_ID)",
                    LOCATION,
                    SUBSCRIPTION_ID),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create H2 cluster with OIDC and workload identity",
                    """
echo "##vso[task.setvariable variable=RESOURCE_GROUP_CREATED]true"
az aks create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(RUN_ID)" \\
  --name wi-webhook \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --dns-name-prefix "$(RUN_ID)" \\
  --tier standard \\
  --control-plane-scaling-size H2 \\
  --enable-managed-identity \\
  --enable-oidc-issuer \\
  --enable-workload-identity \\
  --generate-ssh-keys \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size Standard_D2_v4 \\
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
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(RUN_ID)",
                    SUBSCRIPTION_ID,
                    azure.NodePool {
                        name = "workerpool"
                        sku = "Standard_D2s_v5"
                        count = 3
                        maxPods = 50
                    }),
                kperf.InstallRunkperf(RUNNER_IMAGE),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(RUN_ID)",
                    SUBSCRIPTION_ID,
                    file="$(KUBECONFIG)"),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Prepare WI resources and load profile",
                    """
set -u
profile="$(KPERF_PROFILE)"
client_id=$(az identity create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(RUN_ID)" \\
  --location "${LOCATION}" \\
  --name wi-benchmark \\
  --query clientId \\
  --output tsv)
if ! [[ "$client_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
  echo "Managed identity returned an invalid client ID" >&2
  exit 1
fi
kubectl create namespace "$(RUN_ID)"
kubectl create serviceaccount pod-benchmark --namespace "$(RUN_ID)"
kubectl annotate serviceaccount pod-benchmark \\
  --namespace "$(RUN_ID)" \\
  "azure.workload.identity/client-id=$client_id"

sed \\
  -e 's/__RUN_NAMESPACE__/$(RUN_ID)/g' \\
  -e 's/__RUN_ID__/$(RUN_ID)/g' \\
  "$(Build.SourcesDirectory)/kcl/workload_identity_webhook/load-profile.yaml" > "$profile"
if grep -q '__[A-Z_]*__' "$profile"; then
  echo "Unresolved load-profile placeholders" >&2
  exit 1
fi
"""),
                kperf.RunKperfRunner(
                    profilePath="$(KPERF_PROFILE)",
                    kubeconfig="$(KUBECONFIG)",
                    resultPath="$(KPERF_RESULT)"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RUN_ID)",
                    SUBSCRIPTION_ID,
                    condition="and(always(), eq(variables['RESOURCE_GROUP_CREATED'], 'true'), not(\${{ parameters.keep_cluster }}))"),
            ]
        },
    ]
}
