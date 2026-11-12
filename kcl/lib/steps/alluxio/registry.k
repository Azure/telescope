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
# Record ownership before creation so uncertain CLI results remain recoverable.
printf '##vso[task.setvariable variable=ALLUXIO_ACR_ROLE_ASSIGNMENT_ID]%s\\n' "$role_id"
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
role_id="\${ALLUXIO_ACR_ROLE_ASSIGNMENT_ID:-}"
if [[ -z "$role_id" ]]; then
    echo "No registry grant was created by this run"
    exit 0
fi
roles="$(az role assignment list \\
    --scope "${registryId}" \\
    --subscription "${registrySubscription}")"
jq -e 'type == "array" and all(.[]; .id | type == "string" and length > 0)' <<< "$roles" > /dev/null
if jq -e --arg id "$role_id" 'any(.[]; (.id | ascii_downcase) == ($id | ascii_downcase))' <<< "$roles" > /dev/null; then
    az role assignment delete \\
        --ids "$role_id" \\
        --subscription "${registrySubscription}"
fi
echo '##vso[task.setvariable variable=ALLUXIO_ACR_ROLE_ASSIGNMENT_ID]'
"""
        stepName = "alluxio_acr_cleanup"
        condition = "always()"
    )
}
