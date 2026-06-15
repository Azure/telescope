import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util

# Cl2Benchmark is the "ClusterLoader2 on AKS" scenario archetype.
#
# It captures the small set of scenario-specific knobs (cluster identity,
# cluster requestBody, node pool, optional KWOK nodes, CL2 manifest, result
# JSON) and the archetype `build` lambda fills in the shared spine that every
# CL2 benchmark repeats: run-id -> python deps -> login -> resource group ->
# create cluster -> wait -> node pool -> credentials -> [kwok] -> CL2 ->
# logs -> collect result -> upload -> delete resource group.
#
# Shared defaults are sourced from lib/const so a new scenario only overrides
# what is genuinely different. `requestBody` (the ARM cluster body) is a
# pass-through escape hatch: authors supply raw JSON and the archetype escapes
# it for inline embedding.
schema Cl2Benchmark:
    # Pipeline-level
    name: str
    trigger: [str] = ["v2"]
    pool: str = const.DEFAULT_POOL
    jobName: str = "benchmarking"
    jobDisplayName: str = "Benchmarking"
    timeoutInMinutes: int = 1440

    # Cluster identity
    serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION
    subscription: str = const.DEFAULT_SUBSCRIPTION_ID
    resourceGroup: str = "$(RUN_ID)"
    location: str
    cluster: str

    # Cluster creation
    requestBody: str  # raw ARM managedCluster body (escaped by the archetype)
    clusterApiVersion: str = "2026-01-02-preview"
    useEuapEndpoint: bool = True

    # Workload node pool (the pool CL2 schedules onto)
    nodePool: azure.NodePool

    # Optional KWOK fake nodes (0 = skip)
    kwokNodeCount: int = 0
    kwokNodeManifest: str = ""

    # ClusterLoader2
    cl2Namespace: str
    cl2Manifest: str

    # Result reporting: inner result JSON merged into the Telescope ADX schema
    resultJson: str

    # Result storage (defaults to the shared Telescope account)
    storageAccount: str = const.DEFAULT_STORAGE_ACCOUNT
    storageSubscription: str = const.DEFAULT_STORAGE_SUBSCRIPTION_ID
    storageContainer: str = const.DEFAULT_STORAGE_CONTAINER

# build assembles a Cl2Benchmark config into a full azure_pipelines Pipeline.
build = lambda cfg: Cl2Benchmark -> ap.Pipeline {
    escaped = util.escapeStr(cfg.requestBody)

    euap = "az cloud update --endpoint-resource-manager https://eastus2euap.management.azure.com/\n" if cfg.useEuapEndpoint else ""

    createClusterScript = "\n" + euap + """az rest \\
  --method put \\
  --uri "/subscriptions/${cfg.subscription}/resourceGroups/${cfg.resourceGroup}/providers/Microsoft.ContainerService/managedClusters/${cfg.cluster}?api-version=${cfg.clusterApiVersion}" \\
  --body "${escaped}"
"""

    collectScript = """
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
STATUS="succeeded"

# Check if any cl2 pod failed
FAILED=$(kubectl get pods --namespace="${cfg.cl2Namespace}" -l job-name=cl2 -o jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}' | grep -c "^Failed$" || true)
if [ "$FAILED" -gt 0 ]; then
  STATUS="failed"
fi

cat > /tmp/run-result.json << EOF
${util.formatResult(cfg.resultJson)}
EOF
cat /tmp/run-result.json
"""

    kwokSteps = k8s.CreateKwokNodes(
        cfg.kwokNodeCount,
        params = {"node-manifest-path": cfg.kwokNodeManifest}
    ) if cfg.kwokNodeCount > 0 else []

    ap.Pipeline {
        name = cfg.name
        trigger = cfg.trigger
        pool = cfg.pool

        jobs = [
            job.Job {
                job = cfg.jobName
                displayName = cfg.jobDisplayName
                timeoutInMinutes = cfg.timeoutInMinutes

                steps = [
                    common.SetRunId(),
                    common.InstallPythonDependencies(),
                    azure.Login(
                        cfg.serviceConnection,
                        cfg.subscription,
                        cfg.location),
                    azure.CreateResourceGroup(
                        cfg.serviceConnection,
                        cfg.resourceGroup,
                        cfg.location,
                        cfg.subscription),
                    azure.AzCli(
                        cfg.serviceConnection,
                        "Create cluster",
                        createClusterScript),
                    azure.WaitForClusterSucceeded(
                        cfg.serviceConnection,
                        cfg.cluster,
                        cfg.resourceGroup,
                        cfg.subscription),
                    azure.CreateNodePool(
                        cfg.serviceConnection,
                        cfg.cluster,
                        cfg.resourceGroup,
                        cfg.subscription,
                        cfg.nodePool),
                    azure.GetCredentials(
                        cfg.serviceConnection,
                        cfg.cluster,
                        cfg.resourceGroup,
                        cfg.subscription),
                ] + kwokSteps + [
                    k8s.RunClusterLoader2(
                        cfg.serviceConnection,
                        cfg.cl2Namespace,
                        manifest = cfg.cl2Manifest),
                    k8s.PrintCl2PodLogs(
                        cfg.serviceConnection,
                        cfg.cl2Namespace),
                    azure.AzCli(
                        cfg.serviceConnection,
                        "Collect cl2 pods status",
                        collectScript),
                    common.UploadResult(
                        cfg.serviceConnection,
                        cfg.storageAccount,
                        cfg.storageSubscription,
                        cfg.storageContainer),
                    azure.DeleteResourceGroup(
                        cfg.serviceConnection,
                        cfg.resourceGroup,
                        cfg.subscription),
                ]
            }
        ]
    }
}
