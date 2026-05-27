import azure_pipelines.ap.steps

CreateManagedIdentity = lambda serviceConnection: str, resourceGroup: str, name: str, subscription: str -> steps.Step {
    script = """
az identity create \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}"

IDENTITY_CLIENT_ID=$(az identity show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query clientId -o tsv)
echo "##vso[task.setvariable variable=IDENTITY_CLIENT_ID]$IDENTITY_CLIENT_ID"

IDENTITY_ID=$(az identity show \\
  --resource-group "${resourceGroup}" \\
  --name "${name}" \\
  --subscription "${subscription}" \\
  --query id -o tsv)
echo "##vso[task.setvariable variable=IDENTITY_ID]$IDENTITY_ID"
"""
    AzCli(serviceConnection, "Create managed identity ${name}", script)
}
