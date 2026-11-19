import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.alluxio
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s

# Images and the OCI Helm chart are staged in the existing Telescope registry.
ACR_NAME = "telescope"
ACR_SUBSCRIPTION_ID = "137f0351-8235-42a6-ac7a-6b46be2d21c7"
ALLUXIO_IMAGE_REPOSITORY = "${ACR_NAME}.azurecr.io/alluxio-enterprise"
OPERATOR_IMAGE_REPOSITORY = "${ACR_NAME}.azurecr.io/alluxio-operator"
OPERATOR_CHART_REPOSITORY = "oci://${ACR_NAME}.azurecr.io/helm/alluxio-operator"

# The cluster and the same-region storage account live in LOCATION. westeurope matches the warp
# pipeline, whose subscription is known to have the quota.
LOCATION = "westeurope"
# The cross-region storage account lives in REMOTE_LOCATION. eastus is about 80 ms from westeurope,
# the round trip that makes a cross-region read slow enough for a cache to matter. A region in
# Europe would be closer and shrink the difference being measured.
REMOTE_LOCATION = "eastus"

RESOURCE_GROUP = "alluxio-s3-read-$(RUN_ID)-$(System.JobAttempt)"
CLUSTER = "alluxio-s3-read"
# Storage account names are at most 24 lowercase alphanumerics and globally unique; the build ID
# and job attempt make them unique, and the l/r marker tells the two accounts apart.
LOCAL_ACCOUNT = "alx$(Build.BuildId)l$(System.JobAttempt)"
REMOTE_ACCOUNT = "alx$(Build.BuildId)r$(System.JobAttempt)"
WORK_DIR = "$(Agent.TempDirectory)/alluxio-$(System.JobId)-$(System.JobAttempt)"
RESULT_DIR = "$(Build.ArtifactStagingDirectory)/alluxio-s3-read"
CHECKS_DIR = "$(Build.SourcesDirectory)/kcl/alluxio/s3_read"
# The License manifest is not specific to a workload, so the warp pipeline's copy is reused.
LICENSE_MANIFEST = "$(Build.SourcesDirectory)/kcl/alluxio/warp/license.yaml"
# The UnderFileSystem manifest is not specific to a workload either.
UFS_MANIFEST = "$(Build.SourcesDirectory)/kcl/alluxio/warp/ufs.yaml"

# Three pools keep the load generators off the Alluxio workers. Each value is defined once and
# used both to create the pool and to record it in configuration.json.
# 3 system nodes: etcd needs at least 2, and the warp pipeline uses 3 on the same SKU.
SYSTEM_POOL = azure.NodePool {
    name = "systempool"
    sku = "Standard_D8s_v6"
    count = 3
}
# One worker per client node, so each client has its own worker and the page store is spread
# evenly. 16 concurrent GETs from one client and the checkpoint load from every client exceed
# what the network of a single worker can carry. D16ds_v6 has two 440 GiB local NVMe disks and the page
# store uses one; Managed keeps AKS from taking a disk for an ephemeral OS disk.
WORKER_POOL = azure.NodePool {
    name = "workerpool"
    sku = "Standard_D16ds_v6"
    count = alluxio.S3_READ_WORKER_COUNT
    taintPrefix = "alluxio"
    osDiskType = "Managed"
}
# One client per worker. The checkpoint load reads from all of them at the same time.
# The taint prefix matches the warp pipeline.
CLIENT_POOL = azure.NodePool {
    name = "clientpool"
    sku = "Standard_D8s_v6"
    count = alluxio.S3_READ_CLIENT_COUNT
    taintPrefix = "warp"
}

output = ap.Pipeline {
    name = "Alluxio S3 read vs Azure Blob"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    jobs = [job.Job {
        job = "alluxio_s3_read"
        displayName = "Alluxio S3 API reads compared with direct Azure Blob reads"
        # About 3 hours are expected: 60 minutes setup and data generation, about 105 minutes for
        # scenarios 1-10 with warm-up and gaps (103 minutes in a full run), 15 minutes for scenarios
        # 11-12, then the resource group delete. 240 minutes is that estimate plus a margin.
        timeoutInMinutes = 240
        cancelTimeoutInMinutes = 30
        steps = [
            common.SetRunId()
            k8s.InstallHelm()
            steps.Task {
                task = "KubeloginInstaller@0"
                displayName = "Install kubelogin"
            }
            alluxio.RecordRunConfiguration(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_NAME
                ACR_SUBSCRIPTION_ID
                ALLUXIO_IMAGE_REPOSITORY
                OPERATOR_IMAGE_REPOSITORY
                OPERATOR_CHART_REPOSITORY
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                LOCATION
                LOCAL_ACCOUNT
                WORK_DIR
                RESULT_DIR
                alluxio.RecordedBenchmark {
                    # Published per-VM network limits: D8s_v6 and D16ds_v6 are both 12,500 Mbps.
                    nodePools = alluxio.RecordedNodePools {
                        support = alluxio.RecordedNodePool {pool = SYSTEM_POOL, maxEgressMbpsPerVm = 12500}
                        worker = alluxio.RecordedNodePool {pool = WORKER_POOL, maxEgressMbpsPerVm = 12500}
                        client = alluxio.RecordedNodePool {pool = CLIENT_POOL, maxEgressMbpsPerVm = 12500}
                    }
                    # Must equal pagestore.size and pagestore.reservedSize in cluster.yaml.
                    workerCache = "396Gi"
                    workerCacheReserved = "1Gi"
                    clientVersionKey = "curl_version"
                    # Must equal the curlimages/curl tag in clients.yaml.
                    clientVersion = "8.12.1"
                }
            )
            azure.CreateResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                LOCATION
                const.DEFAULT_SUBSCRIPTION_ID
            )
            azure.AzCli(
                const.DEFAULT_SERVICE_CONNECTION
                "Create cluster"
                """
az aks create \\
  --subscription "${const.DEFAULT_SUBSCRIPTION_ID}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --name "${CLUSTER}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.36" \\
  --nodepool-name ${SYSTEM_POOL.name} \\
  --node-count ${SYSTEM_POOL.count} \\
  --node-vm-size ${SYSTEM_POOL.sku} \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --enable-managed-identity \\
  --enable-aad \\
  --enable-azure-rbac \\
  --disable-local-accounts \\
  --no-ssh-key \\
  --tier standard \\
  --yes
"""
            )
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                WORKER_POOL
            )
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                CLIENT_POOL
            )
            azure.GetCredentials(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
            )
            azure.AzCli(
                const.DEFAULT_SERVICE_CONNECTION
                "Convert kubeconfig to Entra ID login"
                'kubelogin convert-kubeconfig -l azurecli'
            )
            alluxio.ConfigureImagePullAccess(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_NAME
                ACR_SUBSCRIPTION_ID
                WORK_DIR
                RESULT_DIR
            )
            alluxio.SeedS3ReadData(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                LOCATION
                REMOTE_LOCATION
                LOCAL_ACCOUNT
                REMOTE_ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            # The page-store disk must be mounted before the workers start.
            alluxio.PrepareWorkerNvme(
                const.DEFAULT_SERVICE_CONNECTION
                "${CHECKS_DIR}/nvme.yaml"
                WORK_DIR
                RESULT_DIR
            )
            alluxio.InstallOperator(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_NAME
                ACR_SUBSCRIPTION_ID
                OPERATOR_IMAGE_REPOSITORY
                OPERATOR_CHART_REPOSITORY
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateAlluxioCluster(
                const.DEFAULT_SERVICE_CONNECTION
                ALLUXIO_IMAGE_REPOSITORY
                "${CHECKS_DIR}/cluster.yaml"
                LICENSE_MANIFEST
                WORK_DIR
                RESULT_DIR
            )
            alluxio.MountBlobStorage(
                const.DEFAULT_SERVICE_CONNECTION
                LOCAL_ACCOUNT
                "s3-data"
                "LOCAL_DATA_SAS"
                "/blob"
                UFS_MANIFEST
                WORK_DIR
                RESULT_DIR
            )
            alluxio.MountBlobStorage(
                const.DEFAULT_SERVICE_CONNECTION
                REMOTE_ACCOUNT
                "s3-data"
                "REMOTE_DATA_SAS"
                "/xregion"
                UFS_MANIFEST
                WORK_DIR
                RESULT_DIR
            )
            alluxio.MountBlobStorage(
                const.DEFAULT_SERVICE_CONNECTION
                LOCAL_ACCOUNT
                "checkpoint"
                "CHECKPOINT_READ_SAS"
                "/ckpt"
                UFS_MANIFEST
                WORK_DIR
                RESULT_DIR
            )
            alluxio.CreateS3ReadClients(
                const.DEFAULT_SERVICE_CONNECTION
                "${CHECKS_DIR}/clients.yaml"
                "${CHECKS_DIR}/s3c.sh"
                WORK_DIR
                RESULT_DIR
            )
            alluxio.SeedCheckpointSets(
                const.DEFAULT_SERVICE_CONNECTION
                LOCAL_ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            common.RecordCurrentTime("BENCHMARK_START_TIME")
            *[alluxio.RunS3ReadScenarios(
                const.DEFAULT_SERVICE_CONNECTION
                LOCAL_ACCOUNT
                REMOTE_ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
                ids
            ) for ids in alluxio.S3_READ_SCENARIO_GROUPS]
            alluxio.RunCheckpointLoad(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                LOCAL_ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            common.RecordCurrentTime("BENCHMARK_END_TIME")
            alluxio.SummarizeS3Read(
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            alluxio.CollectDiagnostics(
                const.DEFAULT_SERVICE_CONNECTION
                WORK_DIR
                RESULT_DIR
            )
            alluxio.RefuseSasInResults(
                WORK_DIR
                RESULT_DIR
            )
            steps.Task {
                task = "PublishPipelineArtifact@1"
                displayName = "Publish S3 read results and diagnostics"
                condition = "always()"
                inputs = {
                    targetPath = RESULT_DIR
                    artifact = "alluxio-s3-read-$(System.JobAttempt)"
                }
            }
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                condition = "and(always(), eq(variables['SHOULD_CLEAN_UP_RESOURCE_GROUP'], 'true'))"
            )
        ]
    }]
}
