import azure_pipelines.ap.steps
import lib.steps.azure

# RecordedNodePool is a pool written to configuration.json with its VM size's published network
# limit, the maximum bandwidth per VM across all NICs (the "Max Network Bandwidth" column in the
# size series' Network tab, e.g.
# https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dsv6-series#tab/sizenetwork).
schema RecordedNodePool:
    pool: azure.NodePool
    maxEgressMbpsPerVm: int

# RecordedNodePools are the pools whose sizes are written to configuration.json.
schema RecordedNodePools:
    support: RecordedNodePool
    worker: RecordedNodePool
    client: RecordedNodePool

WARP_NODE_POOLS = RecordedNodePools {
    support = RecordedNodePool {
        pool = azure.NodePool {
            name = "systempool"
            sku = "Standard_D8s_v6"
            count = 3
        }
        maxEgressMbpsPerVm = 12500
    }
    worker = RecordedNodePool {
        pool = azure.NodePool {
            name = "workerpool"
            sku = "Standard_D16s_v6"
            count = 1
        }
        maxEgressMbpsPerVm = 12500
    }
    client = RecordedNodePool {
        pool = azure.NodePool {
            name = "clientpool"
            sku = "Standard_D8s_v6"
            count = 1
        }
        maxEgressMbpsPerVm = 12500
    }
}

# RecordedBenchmark is the benchmark-specific part of configuration.json: the node pools, the
# worker page-store sizes and the version of the load-generating client. Callers pass their own;
# the default is the warp pipeline's record. clientVersionKey names the JSON field that holds
# clientVersion (warp_version for warp, curl_version for the S3 read pipeline). clientImage, when set,
# is the client's image in the Telescope registry; its digest is recorded with the Alluxio and operator
# digests.
schema RecordedBenchmark:
    nodePools: RecordedNodePools
    workerCache: str
    workerCacheReserved: str
    clientVersionKey: "warp_version" | "curl_version"
    clientVersion: str
    clientImage: str = ""

WARP_BENCHMARK = RecordedBenchmark {
    nodePools = WARP_NODE_POOLS
    workerCache = "8Gi"
    workerCacheReserved = "1Gi"
    clientVersionKey = "warp_version"
    clientVersion = "1.3.1"
}

RecordRunConfiguration = lambda serviceConnection: str, registryId: str, registrySubscription: str, alluxioImage: str, operatorImage: str, operatorChart: str, subscription: str, resourceGroup: str, cluster: str, location: str, storageAccount: str, workDir: str, resultDir: str, benchmark: RecordedBenchmark = WARP_BENCHMARK -> steps.Step {
    registryHost = registryId.split("/")[-1] + ".azurecr.io/"
    assert benchmark.clientImage == "" or benchmark.clientImage.startswith(registryHost), "clientImage must be in ${registryHost}, got ${benchmark.clientImage}"
    assert benchmark.clientImage == "" or benchmark.clientImage.endswith(benchmark.clientVersion), "clientImage ${benchmark.clientImage} must carry clientVersion ${benchmark.clientVersion}"
    clientDigest = """
client_digest="$(az acr repository show \\
    --name "$registry_name" \\
    --subscription "${registrySubscription}" \\
    --image "${benchmark.clientImage[len(registryHost):]}" | jq -er '.digest')"
images="$(jq --arg image "${benchmark.clientImage}" --arg digest "$client_digest" '. + {($image): $digest}' <<< "$images")"
""" if benchmark.clientImage else ""
    azure.AzCli(
        serviceConnection
        "Record run configuration and image digests"
        ShellSetup(workDir, resultDir) + """
acr_resource_id="${registryId}"
alluxio_image="${alluxioImage}"
operator_image="${operatorImage}"
subscription="${subscription}"
resource_group="${resourceGroup}"
cluster="${cluster}"
location="${location}"
registry="$(az acr show --name "${registryId.split("/")[-1]}" --subscription "${registrySubscription}")"
registry_name="$(jq -er '.name' <<< "$registry")"
images='{}'
for image in "$alluxio_image" "$operator_image"; do
    tag="${ALLUXIO_TAG}"
    if [[ "$image" == "$operator_image" ]]; then tag="${OPERATOR_TAG}"; fi
    digest="$(az acr repository show \\
        --name "$registry_name" \\
        --subscription "${registrySubscription}" \\
        --image "\${image#*/}:$tag" | jq -er '.digest')"
    images="$(jq --arg image "$image:$tag" --arg digest "$digest" '. + {($image): $digest}' <<< "$images")"
done
${clientDigest}exists="$(az group exists \\
    --name "$resource_group" \\
    --subscription "$subscription")"
[[ "$exists" == false ]] || fail "Resource group already exists or could not be verified; refusing to provision into it"
echo '##vso[task.setvariable variable=ALLUXIO_READY_FOR_PROVISIONING]true'

jq -n \\
    --arg acr_resource_id "$acr_resource_id" --arg acr_subscription "${registrySubscription}" \\
    --arg alluxio_image "$alluxio_image" --arg operator_image "$operator_image" \\
    --arg resource_group "$resource_group" --arg subscription "$subscription" \\
    --arg cluster "$cluster" --arg location "$location" --arg storage_account "${storageAccount}" \\
    --argjson image_digests "$images" \\
    --arg operator_chart "${operatorChart}" \\
    --arg operator_version "${OPERATOR_TAG}" --arg ${benchmark.clientVersionKey} "${benchmark.clientVersion}" \\
    '$ARGS.named + {
        worker_cache: "${benchmark.workerCache}", worker_cache_reserved: "${benchmark.workerCacheReserved}",
        support_nodes: {count: ${benchmark.nodePools.support.pool.count}, sku: "${benchmark.nodePools.support.pool.sku}", max_egress_mbps_per_vm: ${benchmark.nodePools.support.maxEgressMbpsPerVm}},
        worker_nodes: {count: ${benchmark.nodePools.worker.pool.count}, sku: "${benchmark.nodePools.worker.pool.sku}", max_egress_mbps_per_vm: ${benchmark.nodePools.worker.maxEgressMbpsPerVm}},
        client_nodes: {count: ${benchmark.nodePools.client.pool.count}, sku: "${benchmark.nodePools.client.pool.sku}", max_egress_mbps_per_vm: ${benchmark.nodePools.client.maxEgressMbpsPerVm}}
    }' > "${resultDir}/configuration.json"
"""
    )
}
