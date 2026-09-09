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
AKS_PREVIEW_EXTENSION_VERSION = "20.0.0b6"

SIMULATED_NODE_COUNT = 2000
KWOK_NODES_PER_CONTROLLER = 100
RESULT_ARTIFACT = "hyperscale-migration-results"
RESULT_DIR = "$(Build.ArtifactStagingDirectory)/hyperscale-migration"

CLUSTER = "hyperscale-migration-$(Build.BuildId)"
RESOURCE_GROUP = "hyperscale-migration-$(Build.BuildId)"

KWOK_POOL = azure.NodePool {
  name = "kwokpool"
    sku = "Standard_D2_v4"
  count = 20
    taintPrefix = "kwok"
    labels = "kwok=true"
}

installMigrationTool = steps.Script {
    script = """
echo "Install migration tool placeholder"
"""
        displayName = "Install migration tool [placeholder]"
}

createClusterScript = """
az extension add \
  --name aks-preview \
  --version ${AKS_PREVIEW_EXTENSION_VERSION} \
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

migrationScript = """
echo "Migration API placeholder: migrate ${CLUSTER} to \${{ parameters.scaling_size }}"
"""

benchmarkJob = job.Job {
    job = "benchmark"
    displayName = "Create, ingest, migrate, and verify"
    timeoutInMinutes = 1440
    steps = [
        installMigrationTool,
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
        azure.WaitForClusterSucceeded(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID),
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
        *k8s.CreateKwokNodes(
            SIMULATED_NODE_COUNT,
            params = {
                "node-manifest-path": "$(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_migration/kwok-node.yaml"
                "nodes-per-controller": "${KWOK_NODES_PER_CONTROLLER}"
                "node-selector": "kwok=true"
                "node-lease-duration-seconds": "100"
                "pod-play-stage-parallelism": "500"
            }),
        steps.Script {
            script = """
set -euo pipefail
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "##vso[task.setvariable variable=BENCHMARK_START_TIME]$START_TIME"
echo "Ingest fixed 2 GiB workload placeholder"
"""
            displayName = "Ingest fixed 2 GiB workload [placeholder]"
        },
        azure.AzCli(
            const.DEFAULT_SERVICE_CONNECTION,
          "Migration API Call [placeholder]",
            migrationScript),
        azure.GetCredentials(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID),
        steps.Script {
            script = """
set -euo pipefail
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 kwok/kwok.py \
  --action validate \
  --node-count ${SIMULATED_NODE_COUNT} \
  --node-manifest-path $(Pipeline.Workspace)/s/kcl/ccp_team/hyperscale_migration/kwok-node.yaml \
  --nodes-per-controller ${KWOK_NODES_PER_CONTROLLER} \
  --node-selector kwok=true \
  --node-lease-duration-seconds 100 \
  --pod-play-stage-parallelism 500
"""
            workingDirectory = "modules/python"
            displayName = "Validate KWOK nodes after migration"
        },
        steps.Script {
            script = """
echo "Verify ingested objects placeholder"
"""
            displayName = "Verify ingested objects [placeholder]"
        },
        asi_dashboard.PrintAsiDashboardUrl(
            const.DEFAULT_SERVICE_CONNECTION,
            CLUSTER,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID,
            startTime="$(BENCHMARK_START_TIME)"),
        steps.Publish {
            publish = RESULT_DIR
            artifact = RESULT_ARTIFACT
            condition = "always()"
            displayName = "Publish benchmark results"
        },
    ]
}

# This is intentionally a raw YAML-shaped object. The dependency schema types
# timeoutInMinutes as an int, while ADO accepts a parameter expression here.
manualValidationJob = {
    job = "manual_validation"
    displayName = "Verify etcd replication"
    dependsOn = "benchmark"
    condition = "succeeded('benchmark')"
    pool = "server"
    timeoutInMinutes = "\${{ parameters.manual_validation_timeout_minutes }}"
    steps = [
        steps.Task {
            task = "ManualValidation@0"
            inputs = {
                notifyUsers = ""
                instructions = "Use privileged etcdctl access to verify representative ConfigMap, Secret, and Deployment keys on all three members of every shard. Cluster: ${CLUSTER}. Resource group: ${RESOURCE_GROUP}. Target profile: \${{ parameters.scaling_size }}."
                onTimeout = "reject"
            }
            displayName = "Approve etcd replica verification"
        },
    ]
}

cleanupJob = job.Job {
    job = "cleanup"
    displayName = "Cleanup"
    timeoutInMinutes = 60
    dependsOn = ["benchmark", "manual_validation"]
    condition = "always()"
    steps = [
        azure.DeleteResourceGroup(
            const.DEFAULT_SERVICE_CONNECTION,
            RESOURCE_GROUP,
            SUBSCRIPTION_ID,
            condition="and(always(), not(\${{ parameters.keep_cluster }}))"),
        steps.Script {
            script = """
echo "Retained cluster ${CLUSTER} in resource group ${RESOURCE_GROUP}"
"""
            displayName = "Print retained cluster"
            condition = "and(always(), \${{ parameters.keep_cluster }})"
        },
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
            name = "manual_validation_timeout_minutes"
            displayName = "Manual etcd validation timeout (minutes)"
            type = "number"
            default = 60
        }
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark"
            type = "boolean"
            default = False
        }
    ]
    jobs = [benchmarkJob, manualValidationJob, cleanupJob]
}