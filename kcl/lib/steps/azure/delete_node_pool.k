import azure_pipelines.ap.steps
import lib.const

# DeleteNodePool removes one user node pool and returns when AKS has finished deleting it. The command
# waits for the operation by default, so a failure to delete fails the step.
DeleteNodePool = lambda cluster: str, resourceGroup: str, subscription: str, pool: str, serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    script = """
az aks nodepool delete \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${pool}"
"""
    AzCli(serviceConnection, "Delete node pool ${pool}", script)
}
