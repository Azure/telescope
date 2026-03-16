import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "westus2"
CLUSTER = "stg-H8-hyperscale"
CL2_POOL = "cl2pool"
CL2_TAINT_PREFIX = "cl2pool"
CL2_NAMESPACE = "clusterloader2"
KWOK_NODE_COUNT = 8000
SCENARIO_NAME = "hyperscale_pod_scheduling_rate"

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
      "controlPlaneScalingProfile": {"scalingSize": "H8"},
      "kubernetesVersion": "1.33.0",
      "dnsPrefix": "${CLUSTER}-dns",
      "agentPoolProfiles": [
        {
          "name": "systempool",
          "mode": "System",
          "count": 30,
          "vmSize": "Standard_D8S_v4",
          "osType": "Linux",
          "maxPods": 250
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
    name = "Example Pipeline"

    trigger =  ["v2"]
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "run_id"
            displayName = "Run ID (leave empty to auto-generate)"
            type = "string"
            default = "default"
        }
    ]

    jobs = [
        job.Job {
            job = "benchmarking"
            displayName = "Benchmarking"
            timeoutInMinutes = 1440

            steps = [
                common.SetRunId(),
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
                    CL2_POOL,
                    "Standard_D8S_v4",
                    4,
                    CL2_TAINT_PREFIX),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    CL2_POOL),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                k8s.CreateKwokNodes(
                  KWOK_NODE_COUNT, 
                  {
                    "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/${SCENARIO_NAME}/kwok-node.yaml"
                  }),
                k8s.RunClusterLoader2(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_NAMESPACE,
                    manifest = "kcl/${SCENARIO_NAME}/cl2.yaml"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
