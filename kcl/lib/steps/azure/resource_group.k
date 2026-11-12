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
    # Azure platform-initiated rolling upgrades (e.g. "VM Agent Rolling Upgrade")
    # block deletion with a 409 ResourceGroupDeletionBlocked / OperationNotAllowed
    # error. Cancel in-progress VMSS rolling upgrades in the AKS node (MC_)
    # resource groups before deleting. This is a no-op when the resource group
    # contains no AKS clusters or no active upgrades.
    script = """
for NODE_RG in $(az aks list \\
  --resource-group "${name}" \\
  --subscription "${subscription}" \\
  --query "[].nodeResourceGroup" \\
  --output tsv); do
  echo "Checking VMSS rolling upgrades in node resource group: $NODE_RG"
  for VMSS in $(az vmss list \\
    --resource-group "$NODE_RG" \\
    --subscription "${subscription}" \\
    --query "[].name" \\
    --output tsv); do
    echo "Attempting to cancel rolling upgrade for VMSS: $VMSS"
    az vmss rolling-upgrade cancel \\
      --resource-group "$NODE_RG" \\
      --name "$VMSS" \\
      --subscription "${subscription}" \\
      && echo "Cancelled rolling upgrade for $VMSS." \\
      || echo "No active rolling upgrade to cancel for $VMSS (or cancel not applicable)."
  done
done

az group delete --name "${name}" --subscription "${subscription}" --yes
"""
    AzCli(
        serviceConnection,
        "Delete resource group (${subscription})",
        script,
        condition = condition)
}
