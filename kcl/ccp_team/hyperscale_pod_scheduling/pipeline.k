import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "southeastasia"
NODE_COUNTS = {"H2": 2000, "H4": 4000, "H8": 8000}
KWOK_NODES_PER_CONTROLLER = 100
makeKwokPool = lambda nodeCount: int -> azure.NodePool {
    azure.NodePool {
        name = "kwokpool"
        sku = "Standard_D4_v3"
        count = nodeCount // KWOK_NODES_PER_CONTROLLER
        taintPrefix = "kwok"
        labels = "kwok=true"
    }
}
CL2_IMAGE = "ghcr.io/azure/clusterloader2:v20260220"
CL2_NAMESPACE = "clusterloader2"
CL2_POOL = azure.NodePool {
    name = "cl2pool"
    sku = "Standard_D16S_v4"
    count = 1
    taintPrefix = "cl2pool"
}

makeBenchmarkingJob = lambda scalingSize: str, cl2Manifest: str -> job.Job {
    nodeCount = NODE_COUNTS[scalingSize]
    kwokPool = makeKwokPool(nodeCount)
    cluster = "stg-${scalingSize}-hyperscale-pod-scheduling-rate"
    createClusterScript = """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes

az aks create \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${cluster}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --dns-name-prefix "${cluster}-dns" \\
  --tier standard \\
  --enable-managed-identity \\
  --enable-aad \\
  --enable-azure-rbac \\
  --disable-local-accounts \\
  --generate-ssh-keys \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size Standard_D8S_v4 \\
  --max-pods 250 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --tags SkipAKSCluster=true SkipASMAzSecPackAutoConfig=true SkipLinuxAzSecPack=true \\
  --control-plane-scaling-size ${scalingSize} \\
  --yes
"""
    job.Job {
        job = "benchmarking"
        displayName = "Benchmarking"
        timeoutInMinutes = 1440

        steps = [
            common.SetRunId(),
            common.InstallPythonDependencies(),
            steps.Task {
                task = "KubeloginInstaller@0"
                displayName = "Install kubelogin"
            },
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
                CL2_POOL),
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID),
            azure.AzCli(
                const.DEFAULT_SERVICE_CONNECTION,
                "Convert kubeconfig to Entra ID login",
                "kubelogin convert-kubeconfig -l azurecli"),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                kwokPool),
            *k8s.CreateKwokNodes(
              const.DEFAULT_SERVICE_CONNECTION,
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
