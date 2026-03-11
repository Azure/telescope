import azure_pipelines.ap.steps

CreateResourceGroup = lambda serviceConnection: str, name: str, location: str, subscription: str -> steps.Step {
    script = """
az group create --name "${name}" --location "${location}" --subscription "${subscription}"
"""
    AzCli(
        serviceConnection,
        "Create resource group ${name} in ${location} (${subscription})",
        script)
}

DeleteResourceGroup = lambda serviceConnection: str, name: str, subscription: str -> steps.Step {
    script = """
az group delete --name "${name}" --subscription "${subscription}" --yes
"""
    AzCli(
        serviceConnection,
        "Delete resource group ${name} (${subscription})",
        script,
        condition = "always()")
}
