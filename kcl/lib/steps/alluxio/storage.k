import azure_pipelines.ap.steps
import lib.steps.azure

SeedWarpDataset = lambda serviceConnection: str, subscription: str, resourceGroup: str, cluster: str, location: str, storageAccount: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Create Blob storage and seed 1 GiB"
        ShellSetup(workDir, resultDir) + SECRET_COMMANDS + """
cluster_info="$(az aks show \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}")"
az storage account create \\
    --name "${storageAccount}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --location "${location}" \\
    --kind StorageV2 \\
    --sku Standard_LRS \\
    --https-only true \\
    --min-tls-version TLS1_2 \\
    --allow-blob-public-access false \\
    --hns false > /dev/null
export AZURE_STORAGE_ACCOUNT="${storageAccount}"
AZURE_STORAGE_KEY="$(private_command az storage account keys list \\
    --account-name "${storageAccount}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" | jq -er '.[0].value')"
export AZURE_STORAGE_KEY
az storage container create \\
    --name warp-data \\
    --public-access off > /dev/null
for ((index = 0; index < 16; index++)); do
    # Fixed per-object keys produce deterministic, nonzero 64 MiB payloads.
    head -c 67108864 /dev/zero |
        openssl enc -aes-256-ctr -K "$(printf '%064x' "$index")" \\
            -iv 00000000000000000000000000000000 > "$work_dir/blob.bin"
    az storage blob upload \\
        --container-name warp-data \\
        --name "$(printf 'object-%02d.bin' "$index")" \\
        --file "$work_dir/blob.bin" \\
        --overwrite false > /dev/null
done
rm -f -- "$work_dir/blob.bin"
az storage blob list --container-name warp-data |
    jq -e -L "${checksDir}" 'include "checks"; validate_dataset' > /dev/null
private_command az storage container generate-sas \\
    --name warp-data \\
    --permissions rl \\
    --expiry "$(date -u -d '+4 hours' +%Y-%m-%dT%H:%MZ)" \\
    --https-only | jq -er 'select(type == "string" and length > 0)' > "$work_dir/blob-sas"
unset AZURE_STORAGE_KEY
jq -n \\
    --arg storage_account "${storageAccount}" --arg container warp-data \\
    --arg location "${location}" --arg kubernetes_version "$(jq -er '.kubernetesVersion' <<< "$cluster_info")" \\
    '$ARGS.named + {object_count: 16, object_bytes: 67108864, total_bytes: 1073741824}' \\
    > "$result_dir/dataset.json"
"""
        stepName = "alluxio_dataset"
    )
}
