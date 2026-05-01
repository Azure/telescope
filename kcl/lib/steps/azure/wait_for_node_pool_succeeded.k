import azure_pipelines.ap.steps

WaitForNodePoolSucceeded = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str, timeoutInMinutes: int = 30 -> steps.Step {
    script = """
while true; do
  STATE=$(az aks nodepool show \\
    --cluster-name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --name "${poolName}" \\
    --query "provisioningState" \\
    --output tsv)
  echo "Node pool provisioning state: $STATE"
  if [ "$STATE" = "Succeeded" ]; then
    echo "Node pool is ready."
    break
  elif [ "$STATE" = "Failed" ] || [ "$STATE" = "Canceled" ]; then
    echo "Node pool failed with state: $STATE."
    exit 1
  else
    echo "Provisioning state: $STATE. Retry in 30 seconds"
  fi
  sleep 30
done
"""
    AzCli(serviceConnection, "Wait for node pool ${poolName} to succeed", script, timeoutInMinutes=timeoutInMinutes)
}
