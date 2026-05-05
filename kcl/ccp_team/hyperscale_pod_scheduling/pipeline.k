import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "southeastasia"
NODE_COUNTS = {"H2": 2000, "H4": 4000, "H8": 8000}
KWOK_NODES_PER_CONTROLLER = 100
KWOK_POOL = "kwokpool"
KWOK_POOL_VM_SIZE = "Standard_D4_v3"
KWOK_POOL_COUNT = 20
CL2_IMAGE = "ghcr.io/azure/clusterloader2:v20260220"
CL2_NAMESPACE = "clusterloader2"
CL2_POOL = "cl2pool"
CL2_TAINT_PREFIX = "cl2pool"

makeRequestBody = lambda scalingSize: str, cluster: str -> str {
    util.escapeStr("""
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
      "controlPlaneScalingProfile": {"scalingSize": "${scalingSize}"},
      "kubernetesVersion": "1.33.0",
      "dnsPrefix": "${cluster}-dns",
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
}

makeBenchmarkingJob = lambda scalingSize: str, cl2Manifest: str -> job.Job {
    nodeCount = NODE_COUNTS[scalingSize]
    cluster = "stg-${scalingSize}-hyperscale-pod-scheduling-rate"
    requestBody = makeRequestBody(scalingSize, cluster)
    createClusterScript = """
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${cluster}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""
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
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                CL2_POOL,
                "Standard_D8S_v4",
                1,
                CL2_TAINT_PREFIX),
            azure.WaitForNodePoolSucceeded(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                CL2_POOL),
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                KWOK_POOL,
                KWOK_POOL_VM_SIZE,
                KWOK_POOL_COUNT,
                "kwok",
                "kwok=true"),
            azure.WaitForNodePoolSucceeded(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                KWOK_POOL),
            *k8s.CreateKwokNodes(
              nodeCount,
              params = {
                "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_pod_scheduling/kwok-node.yaml"
                "nodes-per-controller": "${KWOK_NODES_PER_CONTROLLER}"
                "node-selector": "kwok=true"
                "node-lease-duration-seconds": "100"
                "pod-play-stage-parallelism": "500"
              }),
            k8s.RunClusterLoader2(
                const.DEFAULT_SERVICE_CONNECTION,
                CL2_NAMESPACE,
                manifest = cl2Manifest),
            k8s.PrintCl2PodLogs(
                const.DEFAULT_SERVICE_CONNECTION,
                CL2_NAMESPACE),
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID)
        ]
    }
}

sizes = ["H2", "H4", "H8"]

makeStage = lambda size: str -> ap.Stage {
    ap.Stage {
        stage = size
        displayName = size
        jobs = [makeBenchmarkingJob(size, "kcl/ccp_team/hyperscale_pod_scheduling/cl2-${size.lower()}.yaml")]
    }
}

output = ap.Pipeline {
    name = "Hyperscale Pod Scheduling Rate"

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

    stages = [makeStage(size) for size in sizes]
}
