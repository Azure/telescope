import azure_pipelines.ap.steps
import lib.steps.azure

SeedWarpDataset = lambda serviceConnection: str, subscription: str, resourceGroup: str, cluster: str, location: str, storageAccount: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Create Blob storage and seed 1 GiB"
        ShellSetup(workDir, resultDir) + SecretCommands(workDir) + """
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
            -iv 00000000000000000000000000000000 > "${workDir}/blob.bin"
    az storage blob upload \\
        --container-name warp-data \\
        --name "$(printf 'object-%02d.bin' "$index")" \\
        --file "${workDir}/blob.bin" \\
        --overwrite false > /dev/null
done
rm -f -- "${workDir}/blob.bin"
az storage blob list --container-name warp-data |
    jq -e -L "${checksDir}" 'include "checks"; validate_dataset' > /dev/null
BLOB_SAS="$(az storage container generate-sas \\
    --name warp-data \\
    --permissions rl \\
    --expiry "$(date -u -d '+4 hours' +%Y-%m-%dT%H:%MZ)" \\
    --https-only 2> /dev/null |
    jq -er 'select(type == "string" and length > 0)' 2> /dev/null)" ||
    fail "Could not generate the Blob SAS; secret-bearing output withheld"
unset AZURE_STORAGE_KEY
sas_value="\${BLOB_SAS//'%'/'%AZP25'}"
sas_value="\${sas_value//$'\\n'/'%0A'}"
sas_value="\${sas_value//$'\\r'/'%0D'}"
printf '##vso[task.setvariable variable=BLOB_SAS;issecret=true]%s\\n' "$sas_value"
unset BLOB_SAS sas_value
jq -n \\
    --arg storage_account "${storageAccount}" --arg container warp-data \\
    --arg location "${location}" --arg kubernetes_version "$(jq -er '.kubernetesVersion' <<< "$cluster_info")" \\
    '$ARGS.named + {object_count: 16, object_bytes: 67108864, total_bytes: 1073741824}' \\
    > "${resultDir}/dataset.json"
"""
        stepName = "alluxio_dataset"
    )
}
