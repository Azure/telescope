import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

NODE_SKU = "Standard_D2s_v3"
NODES_PER_POOL = 1000
KUBECONFIG = "$(Agent.TempDirectory)/$(System.JobId)-kubeconfig"

benchmarkJob = lambda region: str -> job.Job {
    cluster = "nodevalidation-$(Build.BuildId)-${region}-nodes${NODES_PER_POOL}-$(System.JobAttempt)"
    workerPools = azure.PlanNodePools(
        {(NODE_SKU): 2 * NODES_PER_POOL}
        maxNodesPerPool=NODES_PER_POOL
    )
    expectedPools = " ".join(["\"${pool.name}:${pool.count}\"" for pool in workerPools])
    job.Job {
        job = "nodes${NODES_PER_POOL}"
        displayName = "Two ${NODES_PER_POOL}-node pools in ${region}"
        condition = "succeeded()"
        timeoutInMinutes = 240
        cancelTimeoutInMinutes = 60
        steps = [
            azure.Login(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                region
            )
            azure.CreateResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                cluster
                region
                const.DEFAULT_SUBSCRIPTION_ID
            )
            azure.AzCli(
                const.DEFAULT_SERVICE_CONNECTION
                "Create Standard-tier cluster"
                """
az aks create \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --resource-group "${cluster}" \\
  --node-resource-group "${cluster}-nodes" \\
  --name "${cluster}" \\
  --location "${region}" \\
  --kubernetes-version "1.36.4" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 2 \\
  --node-vm-size ${NODE_SKU} \\
  --max-pods 250 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --enable-managed-identity \\
  --generate-ssh-keys \\
  --yes
"""
            )
            *[
                azure.CreateNodePool(
                    const.DEFAULT_SERVICE_CONNECTION
                    cluster
                    cluster
                    const.DEFAULT_SUBSCRIPTION_ID
                    pool | {maxPods = 250}
                )
                for pool in workerPools
            ]
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION
                cluster
                cluster
                const.DEFAULT_SUBSCRIPTION_ID
                file=KUBECONFIG
            )
            steps.Bash {
                displayName = "Check worker counts and NoSchedule taints (5-minute polling window)"
                bash = """
bash "$(Build.SourcesDirectory)/kcl/ccp_team/node-validation/wait-for-node-validation.sh" \\
  "${KUBECONFIG}" ${expectedPools}
"""
            }
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                cluster
                const.DEFAULT_SUBSCRIPTION_ID
                condition="and(always(), not(and(\${{ parameters.keep_failed_cluster }}, failed())))"
            )
        ]
    }
}

output = ap.Pipeline {
    name = "node-validation"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "keep_failed_cluster"
            displayName = "Keep the cluster when job fails (manual cleanup required)"
            type = "boolean"
            default = False
        }
    ]
    stages = [
        ap.Stage {
            stage = "eastasia"
            displayName = "East Asia"
            dependsOn = []
            jobs = [
                benchmarkJob("eastasia")
            ]
        }
        ap.Stage {
            stage = "westus2"
            displayName = "West US 2"
            dependsOn = []
            jobs = [
                benchmarkJob("westus2")
            ]
        }
    ]
}
