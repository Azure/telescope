import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

LOCATION = "westus2"
CLUSTER = "nodevalidation-$(Build.BuildId)-$(System.StageName)-$(System.JobAttempt)"
KUBECONFIG = "$(Agent.TempDirectory)/$(System.JobId)-kubeconfig"
RESULTS = "$(Agent.TempDirectory)/node-validation-$(System.JobId)"

benchmarkStage = lambda nodesPerPool: int, predecessor: [str] -> ap.Stage {
    ap.Stage {
        stage = "nodes${nodesPerPool}"
        displayName = "Two ${nodesPerPool}-node pools"
        dependsOn = predecessor
        condition = "succeeded()"
        jobs = [
            job.Job {
                job = "node_validation"
                displayName = "Provision and validate node initialization"
                timeoutInMinutes = 240
                cancelTimeoutInMinutes = 60
                steps = [
                    steps.Bash {
                        displayName = "Record benchmark configuration"
                        bash = """
set -euo pipefail
mkdir -p "${RESULTS}"
jq -n \\
  --arg cluster "${CLUSTER}" \\
  --arg subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --arg location "${LOCATION}" \\
  --arg buildId "$(Build.BuildId)" \\
  --argjson nodesPerPool ${nodesPerPool} \\
  '{cluster: $cluster, resourceGroup: $cluster, subscription: $subscription,
    location: $location, buildId: $buildId, nodesPerPool: $nodesPerPool,
    systemNodes: 2, sku: "Standard_D2_v4", kubernetesVersion: "1.36.4",
    timeoutSeconds: 3600}' | tee "${RESULTS}/configuration.json"
"""
                    }
                    azure.Login(const.DEFAULT_SERVICE_CONNECTION, const.DEFAULT_SUBSCRIPTION_ID, LOCATION)
                    azure.CreateResourceGroup(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, LOCATION, const.DEFAULT_SUBSCRIPTION_ID)
                    azure.AzCli(const.DEFAULT_SERVICE_CONNECTION, "Create Standard-tier cluster", """
az aks create \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --resource-group "${CLUSTER}" \\
  --name "${CLUSTER}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36.4" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 2 \\
  --node-vm-size Standard_D2_v4 \\
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
""")
                    azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, CLUSTER, const.DEFAULT_SUBSCRIPTION_ID, azure.NodePool {
                        name = "workerpool0"
                        sku = "Standard_D2_v4"
                        count = nodesPerPool
                        maxPods = 250
                    })
                    azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, CLUSTER, const.DEFAULT_SUBSCRIPTION_ID, azure.NodePool {
                        name = "workerpool1"
                        sku = "Standard_D2_v4"
                        count = nodesPerPool
                        maxPods = 250
                    })
                    azure.GetCredentials(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, CLUSTER, const.DEFAULT_SUBSCRIPTION_ID, file=KUBECONFIG)
                    steps.Bash {
                        displayName = "Wait up to 60 minutes for Ready, untainted nodes"
                        bash = """
bash "$(Build.SourcesDirectory)/kcl/node-validation/wait-for-node-validation.sh" \\
  "${KUBECONFIG}" ${nodesPerPool} "${RESULTS}"
"""
                    }
                    steps.Bash {
                        displayName = "Collect bounded cloud-node-manager diagnostics"
                        condition = "failed()"
                        bash = """
set -euo pipefail
mkdir -p "${RESULTS}"
if [ ! -f "${KUBECONFIG}" ]; then
  echo "##[warning]No kubeconfig available for node diagnostics"
  exit 0
fi
if ! timeout 30s kubectl --kubeconfig "${KUBECONFIG}" --request-timeout=25s \\
  -n kube-system get daemonset cloud-node-manager -o json \\
  > "${RESULTS}/cloud-node-manager-daemonset.json"; then
  echo "##[warning]Could not collect cloud-node-manager DaemonSet"
fi
if [ ! -f "${RESULTS}/nodes.json" ]; then
  echo "##[warning]No valid node snapshot available for log selection"
  exit 0
fi
if ! timeout 30s kubectl --kubeconfig "${KUBECONFIG}" --request-timeout=25s \\
  -n kube-system get pods -l k8s-app=cloud-node-manager -o json \\
  > "${RESULTS}/cloud-node-manager-pods.json"; then
  echo "##[warning]Could not discover cloud-node-manager pods"
  exit 0
fi
jq -r '
  [.items[]
    | select(any(.spec.taints[]?; .effect == "NoSchedule"))
    | {name: .metadata.name,
       pool: (.metadata.labels.agentpool // .metadata.labels["kubernetes.azure.com/agentpool"])}]
  | group_by(.pool) | .[] | .[0].name' "${RESULTS}/nodes.json" \\
  > "${RESULTS}/diagnostic-nodes.txt"
while read -r node; do
  pod=$(jq -r --arg node "$node" \\
    '[.items[] | select(.spec.nodeName == $node)][0].metadata.name // empty' \\
    "${RESULTS}/cloud-node-manager-pods.json")
  if [ -z "$pod" ]; then
    echo "##[warning]No cloud-node-manager pod found for $node"
    continue
  fi
  if ! timeout 30s kubectl --kubeconfig "${KUBECONFIG}" --request-timeout=25s \\
    -n kube-system logs "$pod" --timestamps --tail=50 \\
    > "${RESULTS}/$pod.log" 2>&1; then
    echo "##[warning]Could not fetch logs for $pod"
  fi
done < "${RESULTS}/diagnostic-nodes.txt"
"""
                    }
                    steps.Task {
                        task = "PublishPipelineArtifact@1"
                        displayName = "Publish node validation evidence"
                        condition = "always()"
                        inputs = {
                            targetPath = RESULTS
                            artifact = "node-validation-$(System.StageName)-$(System.JobAttempt)"
                        }
                    }
                    azure.DeleteResourceGroup(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, const.DEFAULT_SUBSCRIPTION_ID)
                ]
            }
        ]
    }
}

output = ap.Pipeline {
    name = "node-validation"
    trigger = "none"
    pool = const.DEFAULT_POOL
    stages = [
        benchmarkStage(250, [])
        benchmarkStage(500, ["nodes250"])
        benchmarkStage(1000, ["nodes500"])
    ]
}
