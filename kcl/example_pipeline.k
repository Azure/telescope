import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.util

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "telescope-v2-test"
LOCATION = "westus2"
CLUSTER = "stg-H2-yaolei"

requestBody = util.escapeStr("""
{
    "location": "${LOCATION}",
    "identity": { "type": "SystemAssigned" },
    "sku": {
      "name": "Base",
      "tier": "Standard"
    },
    "tags": {
      "exempted_by_qi": "36609072",
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
          "vmSize": "Standard_D8S_v4",
          "osType": "Linux"
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

    jobs = [
        job.Job {
            job = "deploy_to_azure"
            displayName = "Deploy to Azure"

            steps = [
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
                azure.CreateAgentPool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "cl2pool",
                    "Standard_D8S_v4",
                    1),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
