import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s.runkperf
import lib.util

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "uksouth"
CLUSTER = "configmaps100"
RUNNER_IMAGE = "ghcr.io/azure/kperf:0.3.4"

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
      "kubernetesVersion": "1.35",
      "dnsPrefix": "${CLUSTER}-dns",
      "agentPoolProfiles": [
        {
          "name": "default",
          "mode": "System",
          "count": 2,
          "vmSize": "Standard_D2s_v3",
          "osType": "Linux",
          "nodeTaints": ["CriticalAddonsOnly=true:NoSchedule"]
        }
      ],
      "networkProfile": {
        "networkPlugin": "azure",
        "networkPluginMode": "overlay"
      }
    }
  }""")

createClusterScript = """
az rest \\
  --method put \\
  --uri "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER}?api-version=2026-01-02-preview" \\
  --body "${requestBody}"
"""

makeBenchmarkJob = lambda flowcontrol: str, flowcontrolLabel: str -> job.Job {
    job.Job {
        job = "benchmark_${flowcontrolLabel}"
        displayName = "Benchmark (${flowcontrolLabel})"
        timeoutInMinutes = 360

        steps = [
            common.SetRunId(),
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
                "runner",
                "Standard_D16s_v3",
                3),
            azure.WaitForNodePoolSucceeded(
                const.DEFAULT_SERVICE_CONNECTION,
                CLUSTER,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                "runner"),
            runkperf.InstallRunkperf(RUNNER_IMAGE),
            runkperf.RunKperfBenchmark(
                RUNNER_IMAGE,
                flowcontrol,
                "list_configmaps",
                "--total 10000 --size=1024 --group-size=10 --configmap-amount=100"),
            runkperf.CollectKperfResult(
                const.DEFAULT_SERVICE_CONNECTION,
                flowcontrol,
                "--total 10000 --size=1024 --group-size=10 --configmap-amount=100",
                CLUSTER,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID),
            common.UploadResult(
                const.DEFAULT_SERVICE_CONNECTION,
                "telescopev2",
                "137f0351-8235-42a6-ac7a-6b46be2d21c7",
                "aks"),
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID)
        ]
    }
}

makeStage = lambda flowcontrol: str, flowcontrolLabel: str -> ap.Stage {
    ap.Stage {
        stage = flowcontrolLabel
        displayName = flowcontrolLabel
        jobs = [makeBenchmarkJob(flowcontrol, flowcontrolLabel)]
    }
}

output = ap.Pipeline {
    name = "API Server List Configmaps"

    trigger = "none"
    # schedules = [ap.Cron {
    #     cron = "0 3 * * *"
    #     displayName = "Daily 3AM UTC"
    #     branches = ["v2"]
    #     always = True
    # }]
    pool = const.DEFAULT_POOL

    stages = [
        makeStage("workload-low:1000", "workload_low"),
        makeStage("exempt:5", "exempt"),
    ]
}
