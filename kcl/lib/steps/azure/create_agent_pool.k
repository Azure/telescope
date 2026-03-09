import azure_pipelines.ap.steps

CreateAgentPool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str, vmSize: str, count: int -> steps.Step {
    script = """
az aks nodepool add \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${poolName}" \\
  --node-count ${count} \\
  --node-vm-size "${vmSize}" \\
  --mode User
"""
    AzCli(serviceConnection, "Create agent pool ${poolName}", script)
}
