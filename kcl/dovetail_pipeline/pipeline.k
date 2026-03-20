import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s.runkperf
import lib.util

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
DEFAULT_CLUSTER = "dovetail-testing"
LOCATION = "westus2"
NODE_POOL = "workerpool"

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
      "controlPlaneScalingProfile": {"scalingSize": "H2"},
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
az cloud update --endpoint-resource-manager https://eastus2euap.management.azure.com/
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""

output = ap.Pipeline {
    name = "Dovetail Benchmark"

    trigger =  ["v2"]
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "run_id"
            displayName = "Run ID (leave empty to auto-generate)"
            type = "string"
            default = "default"
        }
        ap.Parameter {
            name = "skip_cleanup"
            displayName = "Skip resource cleanup"
            type = "boolean"
            default = "false"
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
    ]

    jobs = [
        job.Job {
            job = "bootstrap"
            displayName = "Bootstrap"
            timeoutInMinutes = 10

            steps = [
                common.Bootstrap(DEFAULT_CLUSTER),
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
                    "Standard_D8S_v4",
                    4),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    NODE_POOL),
            ]
        }
        job.Job {
            job = "benchmark"
            displayName = "Benchmark"
            timeoutInMinutes = 1440
            dependsOn = ["bootstrap", "setup"]
            condition = "or(succeeded(), ${USE_EXISTING_CLUSTER})"
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
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                runkperf.InstallRunkperf("ghcr.io/liyu-ma/kperf:hyperscale-etcd"),
                runkperf.RunKperfDataIngest(
                    namespace="kperf-configmap-data",
                    qps=400,
                    burst=400,
                    name="my-configmaps-500m",
                    total=5000,
                    size=100000,
                    groupSize=50),
            ]
        }
        job.Job {
            job = "cleanup"
            displayName = "Cleanup"
            timeoutInMinutes = 60
            dependsOn = ["bootstrap", "benchmark"]
            condition = "and(always(), not(${USE_EXISTING_CLUSTER}), ne('\${{ parameters.skip_cleanup }}', 'true'))"
            variables = {
                RESOURCE_GROUP = "$[ dependencies.bootstrap.outputs['resolve.RESOURCE_GROUP'] ]"
            }

            steps = [
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
