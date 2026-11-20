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
# An import of the official docker.io/breuner/elbencho image of the same tag; its digest is recorded in
# configuration.json.
ELBENCHO_IMAGE = alluxio.POSIX_BENCHMARK.clientImage

# westeurope matches the warp and S3 read pipelines, whose subscription is known to have the quota.
LOCATION = "westeurope"
RESOURCE_GROUP = "alluxio-posix-read-$(RUN_ID)-$(System.JobAttempt)"
CLUSTER = "alluxio-posix-read"
# Storage account names are at most 24 lowercase alphanumerics and globally unique; the build ID and job
# attempt make this one unique.
ACCOUNT = "alx$(Build.BuildId)p$(System.JobAttempt)"
CONTAINER = "posix-data"
WORK_DIR = "$(Agent.TempDirectory)/alluxio-$(System.JobId)-$(System.JobAttempt)"
RESULT_DIR = "$(Build.ArtifactStagingDirectory)/alluxio-posix-read"
CHECKS_DIR = "$(Build.SourcesDirectory)/kcl/alluxio/posix_read"

# The BlobFuse2 side keeps the mount of its last hot scenario for the cold and concurrent reads, so their
# block size must be the one it was mounted with.
assert all scenario in alluxio.POSIX_SCENARIOS {
    scenario.group not in ["cold", "concurrent"] or scenario.bf2BlockMiB == [hot.bf2BlockMiB for hot in alluxio.POSIX_SCENARIOS if hot.group == "hot"][-1]
}, "the cold and concurrent scenarios must use the BlobFuse2 block size of the last hot scenario"

output = ap.Pipeline {
    name = "Alluxio POSIX read vs BlobFuse2 and DACS"
    trigger = "none"
    pr = "none"
    pool = const.DEFAULT_POOL
    jobs = [job.Job {
        job = "alluxio_posix_read"
        displayName = "Alluxio FUSE reads compared with BlobFuse2 and BlobFuse2 with DACS"
        # About 4 hours are expected, from the steps of a full run: 6 minutes for the cluster and 17 for the data set
        # (a 240 GiB hot pool and about 600 GiB of cold, concurrent-read and re-read files, a set per side); for each
        # of the three sides 35 to 37 minutes of warm-up and hot reads and 17 to 19 for the rest; 24 minutes to set up
        # DACS and 8 to set up Alluxio; then the summary (it waits 6 minutes for the last Egress minute), the
        # diagnostics and the resource group deletion, 20 to 30 minutes. Signing in at the start of each of the 28
        # Azure CLI steps adds a few minutes. 360 minutes leaves more than an hour and a half of margin; no single
        # step runs longer than POSIX_STEP_TIMEOUT_MINUTES.
        timeoutInMinutes = 360
        cancelTimeoutInMinutes = 30
        # Steps that print a failure marker print this pipeline's: PosixFailureMarker renames the marker of the
        # steps shared with the warp and S3 read pipelines. The generic Azure and Kubernetes steps print none.
        steps = [alluxio.PosixFailureMarker(step) for step in [
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
                ACCOUNT
                WORK_DIR
                RESULT_DIR
                alluxio.POSIX_BENCHMARK
            )
            azure.CreateResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                LOCATION
                const.DEFAULT_SUBSCRIPTION_ID
            )
            # --enable-blob-driver installs the Blob CSI driver, which mounts BlobFuse2 for the first two sides.
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
  --nodepool-name ${alluxio.POSIX_BENCHMARK.nodePools.support.pool.name} \\
  --node-count ${alluxio.POSIX_BENCHMARK.nodePools.support.pool.count} \\
  --node-vm-size ${alluxio.POSIX_BENCHMARK.nodePools.support.pool.sku} \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --enable-managed-identity \\
  --enable-aad \\
  --enable-azure-rbac \\
  --disable-local-accounts \\
  --enable-blob-driver \\
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
                alluxio.POSIX_BENCHMARK.nodePools.client.pool
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
            alluxio.GeneratePosixDatasets(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                LOCATION
                ACCOUNT
                CONTAINER
                ELBENCHO_IMAGE
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            common.RecordCurrentTime("BENCHMARK_START_TIME")
            *[alluxio.RunPosixSide(
                const.DEFAULT_SERVICE_CONNECTION
                "bf2"
                CONTAINER
                ELBENCHO_IMAGE
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
                part
            ) for part in alluxio.POSIX_SIDE_PARTS]
            # DACS phase. The DACS Cache selects its nodes by the label; its pods do not tolerate the Alluxio
            # workers' taint, so this pool has none. Its name differs from the Alluxio pool's (see DACS_NODE_POOL).
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                alluxio.POSIX_BENCHMARK.nodePools.worker.pool | {
                    name = alluxio.DACS_NODE_POOL
                    taintPrefix = ""
                    labels = alluxio.DACS_NODE_LABEL
                }
            )
            alluxio.EnableDacs(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                "${CHECKS_DIR}/dacs-cache.yaml"
                WORK_DIR
                RESULT_DIR
            )
            *[alluxio.RunPosixSide(
                const.DEFAULT_SERVICE_CONNECTION
                "dacs"
                CONTAINER
                ELBENCHO_IMAGE
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
                part
            ) for part in alluxio.POSIX_SIDE_PARTS]
            alluxio.EndDacsPhase(
                const.DEFAULT_SERVICE_CONNECTION
                WORK_DIR
                RESULT_DIR
            )
            azure.DeleteNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                alluxio.DACS_NODE_POOL
            )
            # Alluxio phase, on a new cache pool without the DACS label.
            azure.CreateNodePool(
                const.DEFAULT_SERVICE_CONNECTION
                CLUSTER
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                alluxio.POSIX_BENCHMARK.nodePools.worker.pool
            )
            # The pull Secrets created before the data set may be old by now and their token can expire; the
            # Alluxio images are pulled on new nodes in the next steps.
            alluxio.ConfigureImagePullAccess(
                const.DEFAULT_SERVICE_CONNECTION
                ACR_NAME
                ACR_SUBSCRIPTION_ID
                WORK_DIR
                RESULT_DIR
                isRefresh = True
            )
            # The page-store disk must be mounted before the workers start.
            alluxio.PreparePosixWorkerNvme(
                const.DEFAULT_SERVICE_CONNECTION
                "$(Build.SourcesDirectory)/kcl/alluxio/s3_read/nvme.yaml"
                WORK_DIR
                RESULT_DIR
                alluxio.POSIX_BENCHMARK.nodePools.worker.pool.count
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
            # The License and UnderFileSystem manifests are not specific to a workload, so the warp
            # pipeline's copies are reused.
            alluxio.CreatePosixAlluxioCluster(
                const.DEFAULT_SERVICE_CONNECTION
                ALLUXIO_IMAGE_REPOSITORY
                "${CHECKS_DIR}/cluster.yaml"
                "$(Build.SourcesDirectory)/kcl/alluxio/warp/license.yaml"
                WORK_DIR
                RESULT_DIR
            )
            # /posix is the alluxio.fuse.mount.alluxio.path of cluster.yaml.
            alluxio.MountBlobStorage(
                const.DEFAULT_SERVICE_CONNECTION
                ACCOUNT
                CONTAINER
                "POSIX_READ_SAS"
                "/posix"
                "$(Build.SourcesDirectory)/kcl/alluxio/warp/ufs.yaml"
                WORK_DIR
                RESULT_DIR
            )
            alluxio.PrepareAlluxioFuseClients(
                const.DEFAULT_SERVICE_CONNECTION
                "${CHECKS_DIR}/clients-fuse.yaml"
                ELBENCHO_IMAGE
                WORK_DIR
                RESULT_DIR
            )
            *[alluxio.RunPosixSide(
                const.DEFAULT_SERVICE_CONNECTION
                "alluxio"
                ""
                ELBENCHO_IMAGE
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
                part
            ) for part in alluxio.POSIX_SIDE_PARTS]
            common.RecordCurrentTime("BENCHMARK_END_TIME")
            alluxio.SummarizePosixRead(
                const.DEFAULT_SERVICE_CONNECTION
                const.DEFAULT_SUBSCRIPTION_ID
                RESOURCE_GROUP
                CLUSTER
                ACCOUNT
                WORK_DIR
                RESULT_DIR
                CHECKS_DIR
            )
            # Also the DACS servers, the DACS controller and prerequisite DaemonSet, and the Blob CSI node
            # driver, which mounts BlobFuse2 for the first two sides.
            alluxio.CollectDiagnostics(
                const.DEFAULT_SERVICE_CONNECTION
                WORK_DIR
                RESULT_DIR
                ["dacs-cache-system/", "kube-system/dacs-", "kube-system/csi-blob-node-"]
            )
            alluxio.RefuseSasInResults(
                WORK_DIR
                RESULT_DIR
            ) | {name = "posix_sas_check"}
            steps.Task {
                task = "PublishPipelineArtifact@1"
                displayName = "Publish POSIX read results and diagnostics"
                condition = "always()"
                inputs = {
                    targetPath = RESULT_DIR
                    artifact = "alluxio-posix-read-$(System.JobAttempt)"
                }
            }
            azure.DeleteResourceGroup(
                const.DEFAULT_SERVICE_CONNECTION
                RESOURCE_GROUP
                const.DEFAULT_SUBSCRIPTION_ID
                condition = "and(always(), eq(variables['SHOULD_CLEAN_UP_RESOURCE_GROUP'], 'true'))"
            )
        ]]
    }]
}
