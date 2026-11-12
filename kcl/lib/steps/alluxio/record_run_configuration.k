import azure_pipelines.ap.steps
import lib.steps.azure

RecordRunConfiguration = lambda serviceConnection: str, registryId: str, registrySubscription: str, alluxioImage: str, operatorImage: str, operatorChart: str, subscription: str, resourceGroup: str, cluster: str, location: str, storageAccount: str, workDir: str, resultDir: str -> steps.Step {
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
registry="$(az acr show --ids "$acr_resource_id")"
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
exists="$(az group exists \\
    --name "$resource_group" \\
    --subscription "$subscription")"
[[ "$exists" == false ]] || fail "Resource group already exists or could not be verified; refusing to provision into it"

jq -n \\
    --arg acr_resource_id "$acr_resource_id" --arg acr_subscription "${registrySubscription}" \\
    --arg alluxio_image "$alluxio_image" --arg operator_image "$operator_image" \\
    --arg resource_group "$resource_group" --arg subscription "$subscription" \\
    --arg cluster "$cluster" --arg location "$location" --arg storage_account "${storageAccount}" \\
    --argjson image_digests "$images" \\
    --arg operator_chart "${operatorChart}" \\
    --arg operator_version "${OPERATOR_TAG}" --arg warp_version "${WARP_VERSION}" \\
    '$ARGS.named + {
        worker_cache: "8Gi", worker_cache_reserved: "1Gi",
        support_nodes: {count: 2, sku: "Standard_D8s_v5"},
        worker_nodes: {count: 1, sku: "Standard_D16s_v5"},
        client_nodes: {count: 1, sku: "Standard_D8s_v5"}
    }' > "$result_dir/configuration.json"
"""
    )
}
