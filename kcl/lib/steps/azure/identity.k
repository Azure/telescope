import azure_pipelines.ap.steps

CreateManagedIdentity = lambda serviceConnection: str, subscription: str, resourceGroup: str, name: str, exportVar: str = "IDENTITY" -> steps.Step {
    script = """
az identity create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}"

IDENTITY=$(az identity show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}")
echo "##vso[task.setvariable variable=${exportVar}_PRINCIPAL_ID;isOutput=true]$(echo "$IDENTITY" | jq -r '.principalId')"
echo "##vso[task.setvariable variable=${exportVar}_ID;isOutput=true]$(echo "$IDENTITY" | jq -r '.id')"
"""
    AzCli(serviceConnection, "Create managed identity ${name}", script, stepName="createManagedIdentity")
}