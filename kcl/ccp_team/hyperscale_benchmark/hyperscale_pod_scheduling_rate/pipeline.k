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
CLUSTER = "stg-H8-pod-benchmark"
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
          "vmSize": "Standard_D8_v3",
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
    name = "H8 Pod Scheduling Rate Benchmark"

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
                    "node-lease-duration-seconds": "100"
                    "kube-connection-qps": "500.0"
                    "kube-connection-burst": "1000"
                  }),
                k8s.RunClusterLoader2Local(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_IMAGE,
                    cl2OverrideContent,
                    provider = "ks",
                    extraArgs = "--k8s-clients-number=200"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
