import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
SCENARIO = "$(Build.SourcesDirectory)/kcl/workload_identity_webhook"
ARTIFACTS = "$(Build.ArtifactStagingDirectory)/wi-webhook"
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
            job = "setup"
            displayName = "Provision H2 cluster and worker pool"
            timeoutInMinutes = 180
            cancelTimeoutInMinutes = 10
            steps = [
                steps.Bash {
                    bash = """
set -euo pipefail
mkdir -p "${ARTIFACTS}"
echo "##vso[task.setvariable variable=RUN_ID;isOutput=true]wi-$(Build.BuildId)-$(System.JobAttempt)"
"""
                    name = "resolve"
                    displayName = "Resolve run-owned resource group"
                },
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Check AKS version, VM eligibility, and quota",
                    """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes
az aks get-versions \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --output json > "${ARTIFACTS}/kubernetes-versions.json"
jq -e '.values | any(.version | startswith("1.36."))' \\
  "${ARTIFACTS}/kubernetes-versions.json"
az vm list-skus \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --resource-type virtualMachines \\
  --all \\
  --output json > "${ARTIFACTS}/vm-skus.json"
az vm list-usage \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --output json > "${ARTIFACTS}/vm-usage.json"
python3 "${SCENARIO}/preflight.py" "${ARTIFACTS}"
exists=$(az group exists --subscription "${SUBSCRIPTION_ID}" --name "$(resolve.RUN_ID)")
if [ "$exists" != "false" ]; then
  echo "Refusing to reuse an existing or unverified resource group: $(resolve.RUN_ID)" >&2
  exit 1
fi
"""),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(resolve.RUN_ID)",
                    LOCATION,
                    SUBSCRIPTION_ID,
                    tags="benchmark=wi-webhook run_id=$(resolve.RUN_ID) definition_id=$(System.DefinitionId)"),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create H2 cluster with OIDC and workload identity",
                    """
az aks create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(resolve.RUN_ID)" \\
  --name "wi-webhook" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --dns-name-prefix "$(resolve.RUN_ID)" \\
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
                azure.WaitForClusterSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(resolve.RUN_ID)",
                    SUBSCRIPTION_ID),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(resolve.RUN_ID)",
                    SUBSCRIPTION_ID,
                    azure.NodePool {
                        name = "workerpool"
                        sku = "Standard_D8s_v5"
                        count = 3
                        maxPods = 50
                    }),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(resolve.RUN_ID)",
                    SUBSCRIPTION_ID,
                    "workerpool"),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Capture cluster configuration and create benchmark identity",
                    """
az aks show \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(resolve.RUN_ID)" \\
  --name wi-webhook \\
  --output json > "${ARTIFACTS}/cluster-before.json"
jq -e '
  .location == "westus2" and .sku.tier == "Standard"
  and .controlPlaneScalingProfile.scalingSize == "H2"
  and .oidcIssuerProfile.enabled == true
  and .securityProfile.workloadIdentity.enabled == true
  and (.agentPoolProfiles | length == 2)
  and (.agentPoolProfiles | any(.name == "systempool" and .count == 3 and .vmSize == "Standard_D2_v4"))
  and (.agentPoolProfiles | any(.name == "workerpool" and .count == 3 and .vmSize == "Standard_D8s_v5"))
' "${ARTIFACTS}/cluster-before.json"
az identity create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$(resolve.RUN_ID)" \\
  --location "${LOCATION}" \\
  --name wi-benchmark \\
  --output json > "${ARTIFACTS}/identity.json"
client_id=$(jq -er '.clientId | select(type == "string" and length > 0)' "${ARTIFACTS}/identity.json")
echo "##vso[task.setvariable variable=CLIENT_ID;isOutput=true]$client_id"
""",
                    stepName="identity"),
                steps.Task {
                    task = "PublishPipelineArtifact@1"
                    displayName = "Publish setup evidence"
                    condition = "always()"
                    inputs = {
                        targetPath = ARTIFACTS
                        artifact = "wi-setup-$(System.JobAttempt)"
                    }
                },
            ]
        },
        job.Job {
            job = "storage_preflight"
            displayName = "Approve current H2 storage headroom before load"
            dependsOn = "setup"
            pool = "server"
            timeoutInMinutes = 65
            variables = {
                RUN_ID = "$[ dependencies.setup.outputs['resolve.RUN_ID'] ]"
            }
            steps = [
                steps.Task {
                    task = "ManualValidation@0"
                    timeoutInMinutes = 60
                    inputs = {
                        notifyUsers = "$(Build.RequestedForEmail)"
                        instructions = """
Before resuming, inspect current H2 control-plane/storage telemetry for:
subscription ${SUBSCRIPTION_ID}, region ${LOCATION},
resource group $(RUN_ID), cluster wi-webhook.
Record the telemetry source, observation time, available storage, and approved
safety margin in the approval comments. Allow for 360,000 retained Pods plus
warm-up and drain. Submitted JSON alone is about 1.37 GiB; WI/defaulting,
revision history, events, and storage overhead require additional headroom.
Confirm no scheduler handles kperf-admission-only and capture the actual
managed WI webhook resource/replica baseline if available.
Reject if storage visibility or an approved margin is missing. This is NOT a
claim that a fixed number of Pods is safe for H2. No load has started yet.
"""
                        onTimeout = "reject"
                    }
                },
            ]
        },
        job.Job {
            job = "benchmark"
            displayName = "Smoke, warm up, and run custom 600/sec profile"
            dependsOn = ["setup", "storage_preflight"]
            timeoutInMinutes = 60
            cancelTimeoutInMinutes = 10
            variables = {
                RUN_ID = "$[ dependencies.setup.outputs['resolve.RUN_ID'] ]"
                CLIENT_ID = "$[ dependencies.setup.outputs['identity.CLIENT_ID'] ]"
                KUBECONFIG = "$(Agent.TempDirectory)/$(RUN_ID).kubeconfig"
            }
            steps = [
                steps.Bash {
                    bash = "mkdir -p \"${ARTIFACTS}\""
                    displayName = "Create artifact directory"
                },
                common.InstallPythonDependencies(),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "wi-webhook",
                    "$(RUN_ID)",
                    SUBSCRIPTION_ID,
                    file="$(KUBECONFIG)"),
                steps.Bash {
                    bash = """
set -euo pipefail
kubectl wait nodes --all --for=condition=Ready --timeout=300s
kubectl get mutatingwebhookconfigurations -o json > "${ARTIFACTS}/admission-webhooks-before.json"
python3 "${SCENARIO}/benchmark.py" prepare \\
  --run-id "$(RUN_ID)" \\
  --client-id "$(CLIENT_ID)" \\
  --image "${RUNNER_IMAGE}" \\
  --artifacts "${ARTIFACTS}"
"""
                    displayName = "Prepare isolated runner and custom load profiles"
                },
                *[
                    steps.Bash {
                        bash = """
set -euo pipefail
python3 "${SCENARIO}/benchmark.py" run \\
  --phase "${phase}" \\
  --run-id "$(RUN_ID)" \\
  --client-id "$(CLIENT_ID)" \\
  --artifacts "${ARTIFACTS}"
"""
                        displayName = "Run ${phase} profile"
                    } for phase in ["smoke", "warmup", "measure"]
                ],
                steps.Bash {
                    bash = """
set -euo pipefail
python3 "${SCENARIO}/benchmark.py" collect \\
  --run-id "$(RUN_ID)" \\
  --artifacts "${ARTIFACTS}"
"""
                    displayName = "Collect diagnostics and stop any active runner"
                    condition = "always()"
                },
                steps.Task {
                    task = "PublishPipelineArtifact@1"
                    displayName = "Publish benchmark results and diagnostics"
                    condition = "always()"
                    inputs = {
                        targetPath = ARTIFACTS
                        artifact = "wi-benchmark-$(System.JobAttempt)"
                    }
                },
                steps.Bash {
                    bash = "rm -f -- \"$(KUBECONFIG)\""
                    displayName = "Remove run-specific agent kubeconfig"
                    condition = "always()"
                },
            ]
        },
        job.Job {
            job = "finalize"
            displayName = "Retain or delete run-owned resources"
            dependsOn = ["setup", "storage_preflight", "benchmark"]
            condition = "always()"
            timeoutInMinutes = 90
            cancelTimeoutInMinutes = 10
            variables = {
                RUN_ID = "$[ dependencies.setup.outputs['resolve.RUN_ID'] ]"
            }
            steps = [
                steps.Bash {
                    bash = "mkdir -p \"${ARTIFACTS}\""
                    displayName = "Create finalization artifact directory"
                    condition = "always()"
                },
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Verify resource ownership and record retention decision",
                    """
run_id="$(RUN_ID)"
if ! [[ "$run_id" =~ ^wi-[0-9]+-[0-9]+$ ]]; then
  echo "Missing or invalid setup output; no resources will be deleted." >&2
  exit 1
fi
exists=$(az group exists --subscription "${SUBSCRIPTION_ID}" --name "$run_id")
if [ "$exists" = "false" ]; then
  echo "Run resource group does not exist; no cleanup needed." | tee "${ARTIFACTS}/cleanup.txt"
  exit 0
fi
az group show \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --name "$run_id" \\
  --output json > "${ARTIFACTS}/resource-group.json"
jq -e --arg run "$run_id" --arg definition "$(System.DefinitionId)" \\
  '.tags.benchmark == "wi-webhook" and .tags.run_id == $run and .tags.definition_id == $definition' \\
  "${ARTIFACTS}/resource-group.json"
echo "##vso[task.setvariable variable=OWNED_RESOURCE_GROUP]true"
az aks list \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "$run_id" \\
  --output json > "${ARTIFACTS}/clusters-final.json"
echo "keep_cluster=\${{ parameters.keep_cluster }}; resource_group=$run_id; cluster=wi-webhook" \\
  | tee "${ARTIFACTS}/retention.txt"
echo "Manual cleanup: az group delete --subscription ${SUBSCRIPTION_ID} --name $run_id --yes" \\
  | tee -a "${ARTIFACTS}/retention.txt"
""",
                    condition="always()"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RUN_ID)",
                    SUBSCRIPTION_ID,
                    condition="and(always(), eq(variables['OWNED_RESOURCE_GROUP'], 'true'), not(\${{ parameters.keep_cluster }}))"),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Verify deletion completed",
                    """
exists=$(az group exists --subscription "${SUBSCRIPTION_ID}" --name "$(RUN_ID)")
echo "resource_group_exists=$exists" | tee "${ARTIFACTS}/cleanup.txt"
test "$exists" = "false"
""",
                    condition="and(always(), eq(variables['OWNED_RESOURCE_GROUP'], 'true'), not(\${{ parameters.keep_cluster }}))"),
                steps.Task {
                    task = "PublishPipelineArtifact@1"
                    displayName = "Publish retention and cleanup outcome"
                    condition = "always()"
                    inputs = {
                        targetPath = ARTIFACTS
                        artifact = "wi-finalize-$(System.JobAttempt)"
                    }
                },
            ]
        },
    ]
}
