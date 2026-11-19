import azure_pipelines.ap.steps

GetCredentials = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, file: str = "", useAdminCredentials: bool = False -> steps.Step {
    script = """
az aks get-credentials \\
  --name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --overwrite-existing"""
    script += " \\\n  -f ${file}" if file else ""
    script += " \\\n  --admin" if useAdminCredentials else ""
    script += "\n"
    AzCli(serviceConnection, "Get credentials for ${cluster}", script)
}
