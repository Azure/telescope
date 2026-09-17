import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "swedencentral"

# cl2pool node count per tier. Each cl2 load-driver pod requests 6 CPU, so a
# Standard_D16dS_v4 (16 vCPU) fits ~2 pods; sized to the tier's cl2 completions
# (H2=2, H4=4, H8=6) so utilization stays consistent across tiers.
CL2_NODE_COUNTS = {"H2": 1, "H4": 2, "H8": 3}

KWOK_POOL = azure.NodePool {
    name = "kwokpool"
    sku = "Standard_D8_v3"
    count = 60
    taintPrefix = "kwok"
    labels = "kwok=true"
}

makeCl2Pool = lambda size: str -> azure.NodePool {
    azure.NodePool {
        name = "cl2pool"
        sku = "Standard_D16dS_v4"
        count = CL2_NODE_COUNTS[size]
        taintPrefix = "cl2pool"
    }
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
    --dns-name-prefix "${cluster}-dns" \\
    --tier standard \\
    --enable-managed-identity \\
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
# into the stages comprehension below) so the per-size locals cluster/cl2Pool/
# createClusterScript are defined once and reused across steps — a list
# comprehension can't declare locals, which would force repeating those expressions.
makeBenchmarkingJob = lambda size: str -> job.Job {
    cluster = "stg-${size}-hyperscale-apiserver-seats"
    cl2Pool = makeCl2Pool(size)
    createClusterScript = makeCreateClusterScript(size, cluster)
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
                cl2Pool),
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION,
                cluster,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID,
                KWOK_POOL),
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
                manifest = "kcl/ccp_team/hyperscale_apiserver_executing_seats/cl2-${size.lower()}.yaml"),
            k8s.PrintCl2PodLogs(
                const.DEFAULT_SERVICE_CONNECTION,
                "clusterloader2"),
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION,
                RESOURCE_GROUP,
                SUBSCRIPTION_ID)
        ]
    }
}

output = ap.Pipeline {
    name = "Hyperscale API Server Executing Seats"

    # One stage per scaling size; all three run in a single pipeline execution.
    stages = [
        ap.Stage {
            stage = size
            displayName = size
            jobs = [makeBenchmarkingJob(size)]
        } for size in ["H2", "H4", "H8"]
    ]
}
