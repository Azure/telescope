import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure
import lib.steps.kperf
import lib.util.asi_dashboard

SUBSCRIPTION_ID = "b8ceb4e5-f05b-4562-a9f5-14acb1f24219"
LOCATION = "westus2"
# TODO: Merge custom branch to upstream and use official image
RUNNER_IMAGE = "ghcr.io/liyu-ma/kperf:hyperscale-etcd"

# Condition: true when user provides a complete existing cluster reference (skip create/delete)
USE_EXISTING_CLUSTER = "and(ne('\${{ parameters.existing_cluster_name }}', 'none'), ne('\${{ parameters.existing_cluster_resource_group }}', 'none'))"

RESOLVED_CLUSTER = "$(resolve.CLUSTER)"
RESOLVED_RESOURCE_GROUP = "$(resolve.RESOURCE_GROUP)"

createClusterScript = """
az extension add --name aks-preview --version 20.0.0b6 --allow-preview true --yes

az aks create \\
    --subscription "${SUBSCRIPTION_ID}" \\
    --resource-group "${RESOLVED_RESOURCE_GROUP}" \\
    --name "${RESOLVED_CLUSTER}" \\
    --location "${LOCATION}" \\
    --kubernetes-version "1.36" \\
    --dns-name-prefix "${RESOLVED_CLUSTER}-dns" \\
    --tier standard \\
    --enable-managed-identity \\
    --generate-ssh-keys \\
    --nodepool-name systempool \\
    --node-count 3 \\
    --node-vm-size Standard_D2_v4 \\
    --max-pods 50 \\
    --network-plugin azure \\
    --network-plugin-mode overlay \\
    --pod-cidr 10.64.0.0/10 \\
    --service-cidr 10.0.0.0/16 \\
    --dns-service-ip 10.0.0.10 \\
    --outbound-type managedNATGateway \\
    --nat-gateway-managed-outbound-ip-count 10 \\
    --tags SkipAKSCluster=true \\
    --control-plane-scaling-size \${{ parameters.scaling_size }} \\
    --yes
"""

makeIngestionJob = lambda jobName: str, displayName: str, dataType: str, namespace: str, totalGiB: str -> job.Job {
    job.Job {
        job = jobName
        displayName = displayName
        timeoutInMinutes = 1440
        dependsOn = "setup"
        condition = "and(succeeded(), ne('${totalGiB}', '0'))"
        variables = {
            CLUSTER = "$[ dependencies.setup.outputs['resolve.CLUSTER'] ]"
            RESOURCE_GROUP = "$[ dependencies.setup.outputs['resolve.RESOURCE_GROUP'] ]"
        }
        steps = [
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION,
                "$(CLUSTER)",
                "$(RESOURCE_GROUP)",
                SUBSCRIPTION_ID),
            kperf.InstallRunkperf(RUNNER_IMAGE),
            kperf.RunKperfDataIngest(
                dataType=dataType,
                namespace=namespace,
                name="$(System.JobId)",
                totalGiB=totalGiB),
        ]
    }
}

output = ap.Pipeline {
    name = "Hyperscale Etcd Benchmarking"

    trigger = "none"
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "keep_cluster"
            displayName = "Keep cluster after benchmark"
            type = "boolean"
            default = False
        }
        ap.Parameter {
            name = "existing_cluster_resource_group"
            displayName = "Existing cluster resource group (leave as none to create new)"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "existing_cluster_name"
            displayName = "Existing cluster name (leave as none to create new)"
            type = "string"
            default = "none"
        }
        ap.Parameter {
            name = "scaling_size"
            displayName = "Control plane scaling size"
            type = "string"
            default = "H2"
            values = ["H2", "H4", "H8"]
        }
        ap.Parameter {
            name = "ingest_configmap_gib"
            displayName = "ConfigMap ingest size (GiB)"
            type = "number"
            default = 4
        }
        ap.Parameter {
            name = "ingest_events_gib"
            displayName = "Events ingest size (GiB)"
            type = "number"
            default = 3
        }
        ap.Parameter {
            name = "ingest_secrets_gib"
            displayName = "Secrets ingest size (GiB)"
            type = "number"
            default = 4
        }
    ]

    jobs = [
        job.Job {
            job = "setup"
            displayName = "Cluster Setup"
            timeoutInMinutes = 1440
            steps = [
                Bootstrap(),
                azure.Login(
                    const.DEFAULT_SERVICE_CONNECTION,
                    SUBSCRIPTION_ID,
                    LOCATION
                ),
                azure.CreateResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOLVED_RESOURCE_GROUP,
                    LOCATION,
                    SUBSCRIPTION_ID,
                    condition="and(succeeded(), not(${USE_EXISTING_CLUSTER}))"
                ),
                azure.AzCli(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "Create cluster",
                    createClusterScript,
                    condition="and(succeeded(), not(${USE_EXISTING_CLUSTER}))"),
                azure.WaitForClusterSucceeded(
                    const.DEFAULT_SERVICE_CONNECTION,
                    RESOLVED_CLUSTER,
                    RESOLVED_RESOURCE_GROUP,
                    SUBSCRIPTION_ID),
                steps.Script {
                    script = """
set -euo pipefail
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "Benchmark start time: $START_TIME"
echo "##vso[task.setvariable variable=BENCHMARK_START_TIME;isOutput=true]$START_TIME"
"""
                    displayName = "Record start time"
                    name = "timestamp"
                },
            ]
        },
        makeIngestionJob(
            "ingest_configmap",
            "Ingest ConfigMaps (\${{ parameters.ingest_configmap_gib }} GiB)",
            "configmap",
            "kperf-configmap-data",
            "\${{ parameters.ingest_configmap_gib }}"),
        makeIngestionJob(
            "ingest_events",
            "Ingest Events (\${{ parameters.ingest_events_gib }} GiB)",
            "event",
            "kperf-event-data",
            "\${{ parameters.ingest_events_gib }}"),
        makeIngestionJob(
            "ingest_secrets",
            "Ingest Secrets (\${{ parameters.ingest_secrets_gib }} GiB)",
            "secret",
            "kperf-secret-data",
            "\${{ parameters.ingest_secrets_gib }}"),
        job.Job {
            job = "finalize"
            displayName = "Report and Cleanup"
            timeoutInMinutes = 60
            dependsOn = ["setup", "ingest_configmap", "ingest_events", "ingest_secrets"]
            condition = "always()"
            variables = {
                CLUSTER = "$[ dependencies.setup.outputs['resolve.CLUSTER'] ]"
                RESOURCE_GROUP = "$[ dependencies.setup.outputs['resolve.RESOURCE_GROUP'] ]"
                BENCHMARK_START_TIME = "$[ dependencies.setup.outputs['timestamp.BENCHMARK_START_TIME'] ]"
            }
            steps = [
                asi_dashboard.PrintAsiDashboardUrl(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(CLUSTER)",
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    startTime="$(BENCHMARK_START_TIME)"),
                azure.DeleteResourceGroup(
                    const.DEFAULT_SERVICE_CONNECTION,
                    "$(RESOURCE_GROUP)",
                    SUBSCRIPTION_ID,
                    condition="and(always(), not(${USE_EXISTING_CLUSTER}), not(\${{ parameters.keep_cluster }}))")
            ]
        }
    ]
}
