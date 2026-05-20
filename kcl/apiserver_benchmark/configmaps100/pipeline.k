import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.resources
import azure_pipelines.ap.resources.container as res_container
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s.runkperf

SUBSCRIPTION_ID = const.DEFAULT_SUBSCRIPTION_ID
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "uksouth"
CLUSTER = "configmaps100"
RUNNER_IMAGE = "ghcr.io/azure/kperf:0.3.4"

createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.35" \\
  --node-count 1 \\
  --node-vm-size "Standard_B2s" \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --nodepool-taints "CriticalAddonsOnly=true:NoSchedule" \\
  --tier standard \\
  --tags SkipAKSCluster=true SkipASMAzSecPackAutoConfig=true SkipLinuxAzSecPack=true
"""
# TODO: restore cluster to --node-count 2 --node-vm-size "Standard_D2s_v3"

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
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION,
                CLUSTER,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                file = "$(Pipeline.Workspace)/kubeconfig"),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                CLUSTER,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                "runner",
                # TODO: restore to 3 nodes after testing
                "Standard_D16s_v3",
                1),
            runkperf.RunKperfBenchmark(
                RUNNER_IMAGE,
                "list_configmaps",
                # TODO: restore to --total 10000 --configmap-amount=100 after testing
                "--total 10 --size=1024 --group-size=10 --configmap-amount=10",
                "$(Pipeline.Workspace)/kubeconfig",
                flowcontrol = flowcontrol,
                target = "kperf",
                resultPath = "$(Pipeline.Workspace)/tmp_results.json"),
            azure.CollectKperfResult(
                const.DEFAULT_SERVICE_CONNECTION,
                flowcontrol,
                # TODO: restore to --total 10000 --configmap-amount=100 after testing
                "--total 10 --size=1024 --group-size=10 --configmap-amount=10",
                CLUSTER,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                inputPath = "$(Pipeline.Workspace)/tmp_results.json"),
            common.UploadResult(
                const.DEFAULT_SERVICE_CONNECTION,
                const.DEFAULT_STORAGE_ACCOUNT,
                const.DEFAULT_STORAGE_SUBSCRIPTION_ID,
                const.DEFAULT_STORAGE_CONTAINER),
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

    resources = resources.Resources {
        containers = [res_container.Container {
            container = "kperf"
            image = RUNNER_IMAGE
            volumes = ["/usr/bin/kubectl:/usr/local/bin/kubectl"]
        }]
    }

    # TODO: restore schedule after testing
    # schedules = [ap.Cron {
    #     cron = "0 3 * * 0"
    #     displayName = "Weekly Sunday 3AM UTC"
    #     branches = ["v2"]
    #     always = True
    # }]
    pool = const.DEFAULT_POOL

    stages = [
        makeStage("workload-low:1000", "workload_low"),
        makeStage("exempt:5", "exempt"),
    ]
}
