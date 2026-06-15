import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util

SUBSCRIPTION_ID = const.DEFAULT_SUBSCRIPTION_ID
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "westus2"
CLUSTER = "stg-H2-yaolei"
CL2_POOL = "cl2pool"
CL2_TAINT_PREFIX = "cl2pool"
CL2_NAMESPACE = "clusterloader2"
KWOK_NODE_COUNT = 100

# SkipAKSCluster disables Gatekeeper on ephemeral clusters
createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.35.0" \\
  --dns-name-prefix "${CLUSTER}-dns" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 30 \\
  --node-vm-size "Standard_D8S_v4" \\
  --max-pods 250 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --enable-managed-identity \\
  --generate-ssh-keys
"""

cl2ResultJson = """{
    "cl2_status": "\${STATUS}",
    "region": "${LOCATION}"
  }"""

output = ap.Pipeline {
    name = "Example Pipeline"

    trigger =  ["v2"]
    pool = const.DEFAULT_POOL

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
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID,
                    azure.NodePool {
                      name = CL2_POOL,
                      sku = "Standard_D8S_v4",
                      count = 4,
                      taintPrefix = CL2_TAINT_PREFIX }),
                azure.GetCredentials(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                *k8s.CreateKwokNodes(
                  KWOK_NODE_COUNT,
                  params = {
                    "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/example_pipeline/kwok-node.yaml"
                  }),
                k8s.RunClusterLoader2(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_NAMESPACE,
                    manifest = "kcl/example_pipeline/cl2.yaml"),
                k8s.PrintCl2PodLogs(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CL2_NAMESPACE),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Collect cl2 pods status",
                    """
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
STATUS="succeeded"

# Check if any cl2 pod failed
FAILED=$(kubectl get pods --namespace="${CL2_NAMESPACE}" -l job-name=cl2 -o jsonpath='{range .items[*]}{.status.phase}{"\\n"}{end}' | grep -c "^Failed$" || true)
if [ "$FAILED" -gt 0 ]; then
  STATUS="failed"
fi

cat > /tmp/run-result.json << EOF
${util.formatResult(cl2ResultJson)}
EOF
cat /tmp/run-result.json
"""),
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
    ]
}
