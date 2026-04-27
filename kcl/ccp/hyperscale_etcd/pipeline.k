import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s.runkperf
import lib.util
import lib.util.asi_dashboard
import .bootstrap

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
DEFAULT_CLUSTER = "hyperscale-etcd-testing"
LOCATION = "westus2"
NODE_POOL = "workerpool"
RUNNER_IMAGE = "ghcr.io/liyu-ma/kperf:hyperscale-etcd"

# Condition: true when user provides an existing cluster (skip create/delete)
USE_EXISTING_CLUSTER = "ne('\${{ parameters.existing_cluster_name }}', 'none')"

# ADO runtime variable references (resolved by bootstrap job)
CLUSTER: str = "$(CLUSTER)"
RESOURCE_GROUP = "$(RESOURCE_GROUP)"

requestBody = util.escapeStr("""
{
    "location": "${LOCATION}",
    "identity": { "type": "SystemAssigned" },
    "sku": {
      "name": "Base",
      "tier": "Standard"
    },
    "tags": {
      "SkipAKSCluster": "true",
      "SkipASMAzSecPackAutoConfig": "true",
      "SkipLinuxAzSecPack": "true"
    },
    "properties": {
      "controlPlaneScalingProfile": {"scalingSize": "\${{ parameters.scaling_size }}"},
      "kubernetesVersion": "1.33.0",
      "dnsPrefix": "${CLUSTER}-dns",
      "agentPoolProfiles": [
        {
          "name": "systempool",
          "mode": "System",
          "count": 3,
          "vmSize": "Standard_D2_v4",
          "osType": "Linux",
          "maxPods": 50
        }
      ],
    "networkProfile": {
       "networkPlugin": "azure",
       "networkPluginMode": "overlay",
       "podCidr": "10.64.0.0/10",
       "serviceCidr": "10.0.0.0/16",
       "dnsServiceIP": "10.0.0.10",
       "outboundType": "managedNATGateway",
       "natGatewayProfile": {
          "managedOutboundIPProfile": {
            "count": 10
          }
        }
      }
    }
  }""")

createClusterScript = """
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""

# Common steps for each ingest job (login, get creds, install runkperf)
prepareForIngestion = lambda {
    [
        common.InstallPythonDependencies(),
        azure.GetCredentials(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID),
        runkperf.InstallRunkperf(RUNNER_IMAGE),
    ]
}

INGEST_DEPENDS_ON = ["bootstrap", "setup", "record_start_time"]
INGEST_VARIABLES = {
    CLUSTER = "$[ dependencies.bootstrap.outputs['resolve.CLUSTER'] ]"
    RESOURCE_GROUP = "$[ dependencies.bootstrap.outputs['resolve.RESOURCE_GROUP'] ]"
}

output = ap.Pipeline {
    name = "Hyperscale Etcd Benchmarking"

    trigger = "none"
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "run_id"
            displayName = "Run ID (leave empty to auto-generate)"
            type = "string"
            default = "default"
        }
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "existing_cluster_resource_group"
            displayName = "Existing cluster resource group (leave as none to create new)"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "existing_cluster_name"
            displayName = "Existing cluster name (leave as none to create new)"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "scaling_size"
            displayName = "Control plane scaling size"
            type = "string"
            default = "H2"
            values = ["H2", "H4", "H8"]
        }
        ap.Parameter {
            name = "ingest_configmap_gib"
            displayName = "ConfigMap ingest size (GiB)"
            type = "number"
            default = 4
        }
        ap.Parameter {
            name = "ingest_events_gib"
            displayName = "Events ingest size (GiB)"
            type = "number"
            default = 3
        }
        ap.Parameter {
            name = "ingest_secrets_gib"
            displayName = "Secrets ingest size (GiB)"
            type = "number"
            default = 4
        }
    ]

    jobs = [
        job.Job {
            job = "bootstrap"
            displayName = "Bootstrap"
            timeoutInMinutes = 10
            steps = [
                bootstrap.Bootstrap(DEFAULT_CLUSTER),
            ]
        }
        job.Job {
            job = "setup"
            displayName = "Cluster Setup"
            timeoutInMinutes = 1440
            dependsOn = "bootstrap"
            condition = "and(succeeded(), not(${USE_EXISTING_CLUSTER}))"
            variables = {
                CLUSTER = "$[ dependencies.bootstrap.outputs['resolve.CLUSTER'] ]"
                RESOURCE_GROUP = "$[ dependencies.bootstrap.outputs['resolve.RESOURCE_GROUP'] ]"
            }

            steps = [
                common.InstallPythonDependencies(),
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID
                ),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create cluster",
                    createClusterScript),
                azure.WaitForClusterSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    NODE_POOL,
                    "Standard_D2S_v4",
                    2),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    NODE_POOL),
            ]
        }
        job.Job {
            job = "record_start_time"
            displayName = "Record Benchmark Start Time"
            timeoutInMinutes = 5
            dependsOn = ["bootstrap", "setup"]
            condition = "and(eq(dependencies.bootstrap.result, 'Succeeded'), in(dependencies.setup.result, 'Succeeded', 'Skipped'))"
            steps = [
                steps.Script {
                    script = """
set -euo pipefail
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "Benchmark start time: $START_TIME"
echo "##vso[task.setvariable variable=BENCHMARK_START_TIME;isOutput=true]$START_TIME"
"""
                    displayName = "Record start time"
                    name = "timestamp"
                }
            ]
        }
        job.Job {
            job = "ingest_configmap"
            displayName = "Ingest ConfigMaps (\${{ parameters.ingest_configmap_gib }} GiB)"
            timeoutInMinutes = 1440
            dependsOn = INGEST_DEPENDS_ON
            variables = INGEST_VARIABLES
            steps = prepareForIngestion() + [
                runkperf.RunKperfDataIngest(
                    dataType="configmap",
                    namespace="kperf-configmap-data",
                    name="my-configmaps",
                    totalGib="\${{ parameters.ingest_configmap_gib }}",
                    displayName="Ingest configmap data (\${{ parameters.ingest_configmap_gib }} GiB)"),
            ]
        }
        job.Job {
            job = "ingest_events"
            displayName = "Ingest Events (\${{ parameters.ingest_events_gib }} GiB)"
            timeoutInMinutes = 1440
            dependsOn = INGEST_DEPENDS_ON
            variables = INGEST_VARIABLES
            steps = prepareForIngestion() + [
                runkperf.RunKperfDataIngest(
                    dataType="event",
                    namespace="kperf-event-data",
                    name="my-events",
                    totalGib="\${{ parameters.ingest_events_gib }}",
                    displayName="Ingest event data (\${{ parameters.ingest_events_gib }} GiB)"),
            ]
        }
        job.Job {
            job = "ingest_secrets"
            displayName = "Ingest Secrets (\${{ parameters.ingest_secrets_gib }} GiB)"
            timeoutInMinutes = 1440
            dependsOn = INGEST_DEPENDS_ON
            variables = INGEST_VARIABLES
            steps = prepareForIngestion() + [
                runkperf.RunKperfDataIngest(
                    dataType="secret",
                    namespace="kperf-secret-data",
                    name="my-secrets",
                    totalGib="\${{ parameters.ingest_secrets_gib }}",
                    displayName="Ingest secret data (\${{ parameters.ingest_secrets_gib }} GiB)"),
            ]
        }
        job.Job {
            job = "report"
            displayName = "Print ASI Dashboard URLs"
            timeoutInMinutes = 10
            dependsOn = ["bootstrap", "record_start_time", "ingest_configmap", "ingest_events", "ingest_secrets"]
            condition = "in(dependencies.record_start_time.result, 'Succeeded', 'SucceededWithIssues')"
            variables = {
                CLUSTER = "$[ dependencies.bootstrap.outputs['resolve.CLUSTER'] ]"
                RESOURCE_GROUP = "$[ dependencies.bootstrap.outputs['resolve.RESOURCE_GROUP'] ]"
                BENCHMARK_START_TIME = "$[ dependencies.record_start_time.outputs['timestamp.BENCHMARK_START_TIME'] ]"
            }

            steps = [
                asi_dashboard.PrintAsiDashboardUrl(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    startTime="$(BENCHMARK_START_TIME)"),
            ]
        }
        job.Job {
            job = "cleanup"
            displayName = "Cleanup"
            timeoutInMinutes = 60
            dependsOn = ["bootstrap", "ingest_configmap", "ingest_events", "ingest_secrets", "report"]
            condition = "and(always(), not(${USE_EXISTING_CLUSTER}), not(\${{ parameters.keep_cluster }}))"
            variables = {
                RESOURCE_GROUP = "$[ dependencies.bootstrap.outputs['resolve.RESOURCE_GROUP'] ]"
            }

            steps = [
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
