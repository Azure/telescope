import azure_pipelines.ap.steps

GetCredentials = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, file: str = "" -> steps.Step {
    _fileFlag = " -f ${file}" if file else ""
    script = """
az aks get-credentials \\
  --name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --overwrite-existing${_fileFlag}
"""
    AzCli(serviceConnection, "Get credentials for ${cluster}", script)
}
