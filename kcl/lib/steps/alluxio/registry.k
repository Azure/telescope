import azure_pipelines.ap.steps
import lib.steps.azure

GrantImagePullAccess = lambda serviceConnection: str, registryId: str, registrySubscription: str, subscription: str, resourceGroup: str, cluster: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Grant this cluster image pull access"
        ShellSetup(workDir, resultDir) + """
identity="$(az aks show \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" | jq -er '.identityProfile.kubeletidentity.objectId')"
role_name="$(cat /proc/sys/kernel/random/uuid)"
role_id="${registryId}/providers/Microsoft.Authorization/roleAssignments/$role_name"
# Persist ownership before creation so uncertain CLI receipts remain recoverable.
jq -n --arg id "$role_id" '{id: $id}' > "$work_dir/role.json"
az role assignment create \\
    --name "$role_name" \\
    --assignee-object-id "$identity" \\
    --assignee-principal-type ServicePrincipal \\
    --role AcrPull \\
    --scope "${registryId}" \\
    --subscription "${registrySubscription}" > /dev/null
"""
        stepName = "alluxio_acr_grant"
    )
}

RemoveImagePullAccess = lambda serviceConnection: str, registryId: str, registrySubscription: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Remove this run's ACR pull grant"
        ShellSetup(workDir, resultDir) + """
if [[ ! -f "$work_dir/role.json" ]]; then
    echo "No registry grant was created by this run"
    exit 0
fi
role_id="$(jq -er '.id' "$work_dir/role.json")"
roles="$(az role assignment list \\
    --scope "${registryId}" \\
    --subscription "${registrySubscription}")"
jq -e 'type == "array" and all(.[]; .id | type == "string" and length > 0)' <<< "$roles" > /dev/null
if jq -e --arg id "$role_id" 'any(.[]; (.id | ascii_downcase) == ($id | ascii_downcase))' <<< "$roles" > /dev/null; then
    az role assignment delete \\
        --ids "$role_id" \\
        --subscription "${registrySubscription}"
fi
rm -- "$work_dir/role.json"
"""
        stepName = "alluxio_acr_cleanup"
        condition = "always()"
    )
}
