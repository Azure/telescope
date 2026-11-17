import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "swedencentral"

schema Cl2Config:
    nodeCount: int
    driverCount: int
    memoryRequest: str
    qps: int = 4000
    burst: int = 8000
    podsPerNode: int = 4
    bigGroupSize: int = 1
    mediumGroupSize: int = 1
    smallGroupSize: int = 1

# Preserve per-tier concurrency; H2/H4 fit two drivers per runner node.
# H8 runs eight drivers together on dedicated runner nodes.
CL2_CONFIGS: {str: Cl2Config} = {
    "H2": Cl2Config {
        nodeCount = 1
        driverCount = 2
        memoryRequest = "24Gi"
    }
    "H4": Cl2Config {
        nodeCount = 2
        driverCount = 4
        memoryRequest = "24Gi"
    }
    "H8": Cl2Config {
        nodeCount = 8
        driverCount = 8
        memoryRequest = "32Gi"
        qps = 1500
        burst = 100
        # Eight drivers target ~3M load pods and ~553k Deployments.
        podsPerNode = 25
        bigGroupSize = 7
        mediumGroupSize = 5
        smallGroupSize = 5
    }
}

KWOK_POOL = azure.NodePool {
    name = "kwokpool"
    sku = "Standard_D8_v3"
    count = 60
    taintPrefix = "kwok"
    labels = "kwok=true"
}

makeCreateClusterScript = lambda size: str, cluster: str -> str {
    """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes

az aks create \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --name "${cluster}" \\
    --location "${LOCATION}" \\
    --kubernetes-version "1.36" \\
    --node-os-upgrade-channel none \\
    --dns-name-prefix "${cluster}-dns" \\
    --tier standard \\
    --enable-managed-identity \\
    --enable-aad \\
    --enable-azure-rbac \\
    --disable-local-accounts \\
    --generate-ssh-keys \\
    --nodepool-name systempool \\
    --node-count 3 \\
    --node-vm-size Standard_D8dS_v4 \\
    --max-pods 250 \\
    --network-plugin azure \\
    --network-plugin-mode overlay \\
    --pod-cidr 10.64.0.0/10 \\
    --service-cidr 10.0.0.0/16 \\
    --dns-service-ip 10.0.0.10 \\
    --outbound-type managedNATGateway \\
    --nat-gateway-managed-outbound-ip-count 10 \\
    --tags SkipAKSCluster=true \\
    --control-plane-scaling-size ${size} \\
    --yes
"""
}

# Builds the benchmarking job for one scaling size. Kept as a lambda (not inlined
# into the stages comprehension below) so the per-size locals are defined once
# and reused across steps — a list
# comprehension can't declare locals, which would force repeating those expressions.
makeBenchmarkingJob = lambda size: str -> job.Job {
    cluster = "stg-${size}-hyperscale-apiserver-seats"
    cl2Directory = "kcl/ccp_team/hyperscale_apiserver_executing_seats"
    cl2Config = CL2_CONFIGS[size]
    cl2Pool = azure.NodePool {
        name = "cl2pool"
        sku = "Standard_D16dS_v4"
        count = cl2Config.nodeCount
        taintPrefix = "cl2pool"
    }
    createClusterScript = makeCreateClusterScript(size, cluster)
    job.Job {
        job = "benchmarking"
        displayName = "Benchmarking"
        timeoutInMinutes = 600

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
                cl2Pool),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                KWOK_POOL),
            *k8s.CreateKwokNodes(
                const.DEFAULT_SERVICE_CONNECTION,
                15000,
                continueOnError = True,
                params = {
                    "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_apiserver_executing_seats/kwok-node.yaml"
                    "nodes-per-controller": "100"
                    "node-selector": "kwok=true"
                    "node-lease-duration-seconds": "60"
                    "validate-success-threshold": "0.9"
                    "log-level": "WARNING"
                    # Preserve the experiment's shared create-attempt rate across workers.
                    "node-create-workers": "8"
                    "node-create-qps": "20"
                    if size == "H8":
                        # 15k nodes need more than 200 slots each for ~3M pods plus other workloads.
                        "node-pods": "250"
                }),
            steps.Bash {
                displayName = "Render CL2 manifest"
                workingDirectory = "$(Pipeline.Workspace)/s/${cl2Directory}"
                bash = """
set -euo pipefail
sed \\
    -e 's/__CL2_DRIVER_COUNT__/${cl2Config.driverCount}/g' \\
    -e 's/__CL2_MEMORY_REQUEST__/${cl2Config.memoryRequest}/g' \\
    -e 's/__CL2_QPS__/${cl2Config.qps}/g' \\
    -e 's/__CL2_BURST__/${cl2Config.burst}/g' \\
    -e 's/__CL2_PODS_PER_NODE__/${cl2Config.podsPerNode}/g' \\
    -e 's/__CL2_BIG_GROUP_SIZE__/${cl2Config.bigGroupSize}/g' \\
    -e 's/__CL2_MEDIUM_GROUP_SIZE__/${cl2Config.mediumGroupSize}/g' \\
    -e 's/__CL2_SMALL_GROUP_SIZE__/${cl2Config.smallGroupSize}/g' \\
    cl2.yaml > cl2-rendered.yaml

if grep -q '__CL2_[A-Z_]*__' cl2-rendered.yaml; then
    echo "Unresolved CL2 template placeholders" >&2
    exit 1
fi
"""
            },
            k8s.RunClusterLoader2(
                const.DEFAULT_SERVICE_CONNECTION,
                manifest = "${cl2Directory}/cl2-rendered.yaml"),
            k8s.PrintCl2PodLogs(
                const.DEFAULT_SERVICE_CONNECTION,
                "clusterloader2"),
            azure.DeleteResourceGroupAsync(
                const.DEFAULT_SERVICE_CONNECTION,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                condition = "and(always(), not(\${{ parameters.keep_cluster }}))")
        ]
    }
}

output = ap.Pipeline {
    name = "Hyperscale API Server Executing Seats"

    parameters = [
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark"
            type = "boolean"
            default = False
        }
    ]

    # One stage per scaling size; all three run in a single pipeline execution.
    stages = [
        ap.Stage {
            stage = size
            displayName = size
            jobs = [makeBenchmarkingJob(size)]
        } for size in ["H2", "H4", "H8"]
    ]
}
