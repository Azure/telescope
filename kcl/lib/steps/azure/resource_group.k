import azure_pipelines.ap.steps

CreateResourceGroup = lambda serviceConnection: str, name: str, location: str, subscription: str, tags: str = "" -> steps.Step {
    tagsFlag = " \\\n  --tags ${tags}" if tags else ""
    script = """
az group create \\
  --name "${name}" \\
  --location "${location}" \\
  --subscription "${subscription}"${tagsFlag}
"""
    AzCli(
        serviceConnection,
        "Create resource group in ${location} (${subscription})",
        script)
}

DeleteResourceGroup = lambda serviceConnection: str, name: str, subscription: str, condition: str = "always()" -> steps.Step {
    script = """
az group delete --name "${name}" --subscription "${subscription}" --yes
"""
    AzCli(
        serviceConnection,
        "Delete resource group (${subscription})",
        script,
        condition = condition)
}
