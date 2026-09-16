import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "swedencentral"
CONTROL_PLANE_SCALING_SIZE = "\${{ parameters.scaling_size }}"
CLUSTER = "stg-${CONTROL_PLANE_SCALING_SIZE}-hyperscale-apiserver-seats"

CL2_POOL = azure.NodePool {
    name = "cl2pool"
    sku = "Standard_D16dS_v4"
    count = 10
    taintPrefix = "cl2pool"
}
KWOK_POOL = azure.NodePool {
    name = "kwokpool"
    sku = "Standard_D8_v3"
    count = 60
    taintPrefix = "kwok"
    labels = "kwok=true"
}

createClusterScript = """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes

az aks create \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --resource-group "${RESOURCE_GROUP}" \\
    --name "${CLUSTER}" \\
    --location "${LOCATION}" \\
    --kubernetes-version "1.36" \\
    --dns-name-prefix "${CLUSTER}-dns" \\
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
    --tags SkipAKSCluster=true SkipASMAzSecPackAutoConfig=true SkipLinuxAzSecPack=true \\
    --control-plane-scaling-size ${CONTROL_PLANE_SCALING_SIZE} \\
    --yes
"""

output = ap.Pipeline {
    name = "Hyperscale API Server Executing Seats"

  parameters = [
    ap.Parameter {
      name = "scaling_size"
      displayName = "Control plane scaling size"
      type = "string"
      default = "H8"
      values = ["H2", "H4", "H8"]
    }
  ]

    jobs = [
        job.Job {
            job = "benchmarking"
      displayName = "Benchmarking (${CONTROL_PLANE_SCALING_SIZE})"
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
                  CL2_POOL),
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION,
                    CLUSTER,
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
                    manifest = "kcl/ccp_team/hyperscale_apiserver_executing_seats/cl2-\${{ lower(parameters.scaling_size) }}.yaml"),
                  k8s.PrintCl2PodLogs(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "clusterloader2"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOURCE_GROUP,
                    SUBSCRIPTION_ID)
            ]
        }
    ]
}
