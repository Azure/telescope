import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

NODE_SKU = "Standard_D2s_v3"
KUBECONFIG = "$(Agent.TempDirectory)/$(System.JobId)-kubeconfig"

schema JobConfig:
    nodesPerPool: int
    region: str
    nodeSku: str

benchmarkJob = lambda config: JobConfig, predecessors: [str] -> job.Job {
    cluster = "nodevalidation-$(Build.BuildId)-${config.region}-nodes${config.nodesPerPool}-$(System.JobAttempt)"
    workerPools = azure.PlanNodePools(
        {(config.nodeSku): 2 * config.nodesPerPool}
        maxNodesPerPool=config.nodesPerPool
    )
    expectedPools = " ".join(["\"${pool.name}:${pool.count}\"" for pool in workerPools])
    job.Job {
        job = "nodes${config.nodesPerPool}"
        displayName = "Two ${config.nodesPerPool}-node pools in ${config.region}"
        dependsOn = predecessors
        condition = "succeeded()"
        timeoutInMinutes = 240
        cancelTimeoutInMinutes = 60
        steps = [
            azure.Login(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                config.region
            )
            azure.CreateResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                cluster
                config.region
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
  --location "${config.region}" \\
  --kubernetes-version "1.36.4" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 2 \\
  --node-vm-size ${config.nodeSku} \\
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
                benchmarkJob(
                    JobConfig {
                        nodesPerPool = 1000
                        region = "eastasia"
                        nodeSku = NODE_SKU
                    }
                    []
                )
            ]
        }
        ap.Stage {
            stage = "westus2"
            displayName = "West US 2"
            dependsOn = []
            jobs = [
                benchmarkJob(
                    JobConfig {
                        nodesPerPool = 500
                        region = "westus2"
                        nodeSku = NODE_SKU
                    }
                    []
                )
                benchmarkJob(
                    JobConfig {
                        nodesPerPool = 1000
                        region = "westus2"
                        nodeSku = NODE_SKU
                    }
                    ["nodes500"]
                )
            ]
        }
    ]
}
