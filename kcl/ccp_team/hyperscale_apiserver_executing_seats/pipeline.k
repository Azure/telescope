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
CONTROL_PLANE_SCALING_SIZE = "H8"
CLUSTER = "stg-${CONTROL_PLANE_SCALING_SIZE}-hyperscale-apiserver-seats"

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
      "controlPlaneScalingProfile": {"scalingSize": "${CONTROL_PLANE_SCALING_SIZE}"},
      "kubernetesVersion": "1.33.0",
      "dnsPrefix": "${CLUSTER}-dns",
      "agentPoolProfiles": [
        {
          "name": "systempool",
          "mode": "System",
          "count": 3,
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
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""

output = ap.Pipeline {
    name = "Hyperscale API Server Executing Seats"

    jobs = [
        job.Job {
            job = "benchmarking"
            displayName = "Benchmarking"
            timeoutInMinutes = 600

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
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                azure.CreateNodePool(
                  const.DEFAULT_SERVICE_CONNECTION,
                  CLUSTER,
                  RESOURCE_GROUP,
                  SUBSCRIPTION_ID,
                  "cl2pool",
                  "Standard_D16S_v4",
                  10,
                  "cl2pool"),
                azure.WaitForNodePoolSucceeded(
                  const.DEFAULT_SERVICE_CONNECTION,
                  CLUSTER,
                  RESOURCE_GROUP,
                  SUBSCRIPTION_ID,
                  "cl2pool"),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "kwokpool",
                    "Standard_D8_v3",
                    60,
                    "kwok",
                    "kwok=true"),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    "kwokpool"),
                *k8s.CreateKwokNodes(
                  15000,
                  continueOnError = True,
                  params = {
                    "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_apiserver_executing_seats/kwok-node.yaml"
                    "nodes-per-controller": "100"
                    "node-selector": "kwok=true"
                    "node-lease-duration-seconds": "60"
                    "validate-success-threshold": "0.9"
                    "log-level": "WARNING"
                  }),
                  k8s.RunClusterLoader2(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "clusterloader2",
                    manifest = "kcl/ccp_team/hyperscale_apiserver_executing_seats/cl2.yaml"),
                  k8s.PrintCl2PodLogs(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "clusterloader2"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
