import azure_pipelines.ap.steps

# DeleteNodePool removes one user node pool and returns when AKS has finished deleting it. The command
# waits for the operation by default, so a failure to delete fails the step.
DeleteNodePool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pool: str -> steps.Step {
    script = """
az aks nodepool delete \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${pool}"
"""
    AzCli(serviceConnection, "Delete node pool ${pool}", script)
}
