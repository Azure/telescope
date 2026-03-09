import azure_pipelines.ap.steps

GetCredentials = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str -> steps.Step {
    script = """
az aks get-credentials \\
  --name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --overwrite-existing
"""
    AzCli(serviceConnection, "Get credentials for ${cluster}", script)
}
