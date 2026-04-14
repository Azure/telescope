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
NODE_COUNT = 15000
KWOK_NODES_PER_CONTROLLER = 100
CL2_NAMESPACE = "clusterloader2"
CL2_MANIFEST = "kcl/hyperscale_apiserver_executing_seats/cl2.yaml"
CL2_POOL = "cl2pool"
CL2_POOL_VM_SIZE = "Standard_D16S_v4"
CL2_POOL_COUNT = 2
KWOK_POOL = "kwokpool"
KWOK_POOL_VM_SIZE = "Standard_D8_v3"
KWOK_POOL_COUNT = 60
CL2_IMAGE = "ghcr.io/azure/clusterloader2:v20260220"

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
az cloud update --endpoint-resource-manager https://eastus2euap.management.azure.com/
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""

output = ap.Pipeline {
    name = "Hyperscale API Server Executing Seats"

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
            timeoutInMinutes = 300

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
                  CL2_POOL,
                  CL2_POOL_VM_SIZE,
                  CL2_POOL_COUNT,
                  CL2_POOL),
                azure.WaitForNodePoolSucceeded(
                  const.DEFAULT_SERVICE_CONNECTION,
                  CLUSTER,
                  RESOURCE_GROUP,
                  SUBSCRIPTION_ID,
                  CL2_POOL),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    KWOK_POOL,
                    KWOK_POOL_VM_SIZE,
                    KWOK_POOL_COUNT,
                    "kwok",
                    "kwok=true"),
                azure.WaitForNodePoolSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    KWOK_POOL),
                k8s.CreateKwokNodes(
                  NODE_COUNT,
                  {
                    "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/hyperscale_apiserver_executing_seats/kwok-node.yaml"
                    "group": ""
                    "nodes-per-controller": "${KWOK_NODES_PER_CONTROLLER}"
                    "node-selector-key": "kwok"
                    "node-selector-value": "true"
                    "toleration-key": "kwok"
                    "toleration-value": "true"
                    "node-lease-parallelism": "200"
                    "pod-play-stage-parallelism": "100"
                    "node-play-stage-parallelism": "100"
                    "cidr": "100.64.0.0/10"
                    "node-ip": "100.64.0.1"
                    "node-lease-duration-seconds": "60"
                    "kube-connection-qps": "500.0"
                    "kube-connection-burst": "1000"
                    "node-create-interval-seconds": "0.15"
                  }),
                  k8s.RunClusterLoader2(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_NAMESPACE,
                    manifest = CL2_MANIFEST),
                  k8s.PrintCl2PodLogs(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_NAMESPACE),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
