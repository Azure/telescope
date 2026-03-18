import azure_pipelines.ap.steps

CreateNodePool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str, vmSize: str, count: int, taintPrefix: str = "", labels: str = "" -> steps.Step {
    taintFlag = "--node-taints ${taintPrefix}=true:NoSchedule" if taintPrefix else ""
    labelFlag = "--labels ${labels}" if labels else ""
    script = """
az aks nodepool add \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${poolName}" \\
  --node-count ${count} \\
  --node-vm-size "${vmSize}" \\
  --mode User \\
  ${taintFlag} \\
  ${labelFlag}
"""
    AzCli(serviceConnection, "Create node pool ${poolName}", script)
}
