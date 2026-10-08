import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const as const
import lib.steps.azure as azure
import lib.steps.common as common
import lib.steps.health
import lib.steps.kperf as kperf

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"

# size/count/name configure RunKperfDataIngest; count=0 skips ingest.
# preApply -> optional `kubectl apply -f <file>` before the run (scenario6 loggers).
schema Scenario:
    manifest: str
    size: int = 0
    count: int = 0
    name: str = ""
    preApply: str = ""
    preApplyNamespace: str = ""

schema ClusterConfig:
    region: str
    systemRunnerSku: str
    userPoolSku: str
    customHeaders: str

WorkloadsDir = "kcl/cluster_health_performance/workloads"

# All scenarios run sequentially on the same cluster.
# TODO: Add workloads in the follow-up PR.
WORKLOADS: {str:Scenario} = {}

CLUSTER_NAME = "underlay-validation"
KUBERNETES_VERSION = "\${{ parameters.kubernetes_version }}"

AMD_CONFIG = ClusterConfig {
    region = "westus2"
    systemRunnerSku = "Standard_D8s_v4"
    userPoolSku = "Standard_D2s_v4"
    customHeaders = "ControlPlaneUnderlay=hcp-underlay-stg-westus2-cx-23"
}

INTEL_CONFIG = ClusterConfig {
    region = "westus2"
    systemRunnerSku = "Standard_D8s_v4"
    userPoolSku = "Standard_D2s_v4"
    customHeaders = "ControlPlaneUnderlay=hcp-underlay-stg-westus2-cx-22"
}

CUSTOM_CONFIG = ClusterConfig {
    region = "\${{ parameters.custom_region }}"
    systemRunnerSku = "\${{ parameters.custom_system_runner_vm_sku }}"
    userPoolSku = "\${{ parameters.custom_user_pool_vm_sku }}"
    customHeaders = "\${{ parameters.custom_headers }}"
}

buildJob = lambda config: ClusterConfig -> job.Job {
    job.Job {
        job = "underlay_validation"
        displayName = "Validate underlay"
        timeoutInMinutes = 600
        steps = [
            common.SetRunId()
            azure.Login(const.DEFAULT_SERVICE_CONNECTION, SUBSCRIPTION_ID, config.region)
            azure.CreateResourceGroup(const.DEFAULT_SERVICE_CONNECTION, "$(RUN_ID)", config.region, SUBSCRIPTION_ID)
            # AKS cluster with Azure CNI Overlay.
            azure.AzCli(const.DEFAULT_SERVICE_CONNECTION, "Create AKS cluster", """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --upgrade --yes

EXTRA_ARGS=""
if [ "${config.customHeaders}" != "none" ]; then
    EXTRA_ARGS="--aks-custom-headers ${config.customHeaders}"
fi

az aks create \\
    --name "${CLUSTER_NAME}" \\
  --resource-group "$(RUN_ID)" \\
  --subscription "${SUBSCRIPTION_ID}" \\
    --location "${config.region}" \\
    --kubernetes-version "${KUBERNETES_VERSION}" \\
    --dns-name-prefix "${CLUSTER_NAME}-dns" \\
    --tier standard \\
  --nodepool-name systempool \\
  --node-count 5 \\
    --node-vm-size "${config.systemRunnerSku}" \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.244.0.0/14 \\
  --max-pods 250 \\
  --control-plane-scaling-size H8 \\
  --enable-managed-identity \\
  --generate-ssh-keys \\
  $EXTRA_ARGS
""")
            # runner nodepool (kperf runners).
            azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER_NAME, "$(RUN_ID)", SUBSCRIPTION_ID, azure.NodePool {
                name = "runner"
                sku = config.systemRunnerSku
                count = 5
            })
            # userpool (workload pods).
            azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER_NAME, "$(RUN_ID)", SUBSCRIPTION_ID, azure.NodePool {
                name = "userpool"
                sku = config.userPoolSku
                count = 100
            })
            azure.GetCredentials(const.DEFAULT_SERVICE_CONNECTION, CLUSTER_NAME, "$(RUN_ID)", SUBSCRIPTION_ID)
            health.ValidateWorkloadHealth(const.DEFAULT_SERVICE_CONNECTION, kind="*", namespace="kube-system", continueOnError=True)
            health.ValidateCoreDNS(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            health.ValidateMetricsServer(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            health.ValidateKonnectivityAgent(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            health.ValidateAzureCNS(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            health.ValidateCloudNodeManager(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            health.ValidateCsiNode(const.DEFAULT_SERVICE_CONNECTION, "managed-csi", continueOnError=True)
            health.ValidateCsiNode(const.DEFAULT_SERVICE_CONNECTION, "azurefile-csi", continueOnError=True)
            health.ValidateClusterIPService(const.DEFAULT_SERVICE_CONNECTION, continueOnError=True)
            kperf.InstallRunkperf("ghcr.io/azure/kperf:0.3.6")
            # TODO: Add performance workloads in a follow-up PR.
            # Always tear down the resource group at the end.
            azure.DeleteResourceGroup(const.DEFAULT_SERVICE_CONNECTION, "$(RUN_ID)", SUBSCRIPTION_ID, condition="always()")
        ]
    }
}

makeStage = lambda name: str, displayName: str, config: ClusterConfig -> ap.Stage {
    ap.Stage {
        stage = name
        displayName = displayName
        jobs = [buildJob(config)]
    }
}

output = ap.Pipeline {
    name = "Underlay Validation"
    trigger = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "custom_region"
            displayName = "Custom: Azure region"
            type = "string"
            default = "westus2"
        }
        ap.Parameter {
            name = "kubernetes_version"
            displayName = "Kubernetes version"
            type = "string"
            default = "1.35.5"
        }
        ap.Parameter {
            name = "custom_system_runner_vm_sku"
            displayName = "Custom: system and runner pool VM SKU"
            type = "string"
            default = "Standard_D8s_v4"
        }
        ap.Parameter {
            name = "custom_user_pool_vm_sku"
            displayName = "Custom: user pool VM SKU"
            type = "string"
            default = "Standard_D2s_v4"
        }
        ap.Parameter {
            name = "custom_headers"
            displayName = "Custom: AKS custom headers ('none' to omit)"
            type = "string"
            default = "none"
        }
    ]
    stages = [
        makeStage("amd", "AMD", AMD_CONFIG)
        makeStage("intel", "Intel", INTEL_CONFIG)
        makeStage("custom", "Custom", CUSTOM_CONFIG)
    ]
}
