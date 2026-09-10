import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util.asi_dashboard

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
KUBERNETES_VERSION = "1.36"

CLUSTER = "hyperscale-migration-$(Build.BuildId)"
RESOURCE_GROUP = "hyperscale-migration-$(Build.BuildId)"

KWOK_POOL = azure.NodePool {
    name = "kwokpool"
    sku = "Standard_D8s_v3"
    count = 700
    taintPrefix = "kwok"
    labels = "kwok=true"
}

createClusterScript = """
az extension add \
  --name aks-preview \
  --version 20.0.0b6 \
  --allow-preview true \
  --yes

az aks create \
  --subscription "${SUBSCRIPTION_ID}" \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${CLUSTER}" \
  --location "${LOCATION}" \
  --kubernetes-version "${KUBERNETES_VERSION}" \
  --dns-name-prefix "${CLUSTER}-dns" \
  --tier standard \
  --enable-managed-identity \
  --generate-ssh-keys \
  --nodepool-name systempool \
  --node-count 3 \
  --node-vm-size Standard_D8S_v4 \
  --max-pods 250 \
  --network-plugin azure \
  --network-plugin-mode overlay \
  --pod-cidr 10.64.0.0/10 \
  --service-cidr 10.0.0.0/16 \
  --dns-service-ip 10.0.0.10 \
  --outbound-type managedNATGateway \
  --nat-gateway-managed-outbound-ip-count 10 \
  --tags SkipAKSCluster=true \
  --yes
"""

benchmarkJob = job.Job {
    job = "benchmark"
    displayName = "Create, ingest, migrate, and verify"
    timeoutInMinutes = 1440
    steps = [
        common.InstallPythonDependencies(),
        azure.Login(const.DEFAULT_SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION),
        azure.CreateResourceGroup(
            const.DEFAULT_SERVICE_CONNECTION,
            RESOURCE_GROUP,
            LOCATION,
            SUBSCRIPTION_ID),
        azure.AzCli(
            const.DEFAULT_SERVICE_CONNECTION,
            "Create standard-tier cluster",
            createClusterScript),
        azure.CreateNodePool(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID,
            KWOK_POOL),
        azure.GetCredentials(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID),
        # Create 2,000 simulated nodes across 2000 controllers.
        *k8s.CreateKwokNodes(
            2000,
            params = {
                "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/hyperscale_migration/kwok-node.yaml"
                "nodes-per-controller": "1"
                "node-selector": "kwok=true"
                "node-lease-duration-seconds": "100"
                "pod-play-stage-parallelism": "500"
            }),
        steps.Script {
            script = """
                    echo "Install Go app image"
                    """
            displayName = "Install ingestion client [placeholder]"
        }
        steps.Script {
            script = """
set -euo pipefail
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "##vso[task.setvariable variable=BENCHMARK_START_TIME]$START_TIME"
echo "Ingest fixed 2 GiB workload placeholder"
"""
            displayName = "Ingest data workload for migration [placeholder]"
        },
        azure.AzCli(
            const.DEFAULT_SERVICE_CONNECTION,
          "Record migration start [placeholder]",
                        """
echo "Migration API placeholder: migrate ${CLUSTER} to \${{ parameters.scaling_size }}"
"""),
        steps.Bash {
            bash = """
echo "Wait for migration complete placeholder"
"""
            displayName = "Wait and record migration complete [placeholder]"
        },
        asi_dashboard.PrintAsiDashboardUrl(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID,
            startTime="$(BENCHMARK_START_TIME)"),
        steps.Bash {
            bash = """
echo "Verify ingested objects placeholder"
"""
            displayName = "Verify ingested objects [placeholder]"
        },
        steps.Bash {
            bash = """
echo "Verify etcd shards data with etcdctl placeholder"
"""
            displayName = "Verify etcd shards data (etcdctl)"
        },
        steps.Bash {
            bash = """
echo "Print benchmark summary placeholder"
"""
            displayName = "Print benchmark summary [placeholder]"
        },
        azure.DeleteResourceGroup(
            const.DEFAULT_SERVICE_CONNECTION,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID,
            condition="and(always(), not(\${{ parameters.keep_cluster }}))"),
    ]
}

output = {
    name = "Hyperscale Migration Benchmark"
    trigger = "none"
    pool = const.DEFAULT_POOL
    parameters = [
        ap.Parameter {
            name = "scaling_size"
            displayName = "Control plane scaling size"
            type = "string"
            default = "H2"
            values = ["H2", "H4", "H8"]
        }
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark"
            type = "boolean"
            default = False
        }
    ]
    jobs = [benchmarkJob]
}