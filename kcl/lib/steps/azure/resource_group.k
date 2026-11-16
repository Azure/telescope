import azure_pipelines.ap.steps

CreateResourceGroup = lambda serviceConnection: str, name: str, location: str, subscription: str, tags: str = "", condition: str = Undefined -> steps.Step {
    script = """
az group create \\
  --name "${name}" \\
  --location "${location}" \\
  --subscription "${subscription}" \\
${"--tags " + tags if tags else ""}
"""
    AzCli(
        serviceConnection,
        "Create resource group in ${location} (${subscription})",
        script,
        condition = condition)
}

# Submits asynchronously, then waits for deletion with rolling-upgrade recovery.
DeleteResourceGroupAsync = lambda serviceConnection: str, name: str, subscription: str, condition: str = "always()", timeoutSeconds: int = 2700, pollIntervalSeconds: int = 30 -> steps.Step {
    assert timeoutSeconds > 0 and pollIntervalSeconds > 0, "Timeout and poll interval must be positive"
    AzCli(
        serviceConnection,
        "Delete resource group with rolling-upgrade recovery (${subscription})",
        """
python3 "$(Build.SourcesDirectory)/kcl/lib/steps/azure/resource_group.py" delete \\
  --resource-group "${name}" \\
  --subscription "${subscription}" \\
  --timeout-seconds ${timeoutSeconds} \\
  --poll-interval-seconds ${pollIntervalSeconds}
""",
        condition = condition)
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
