import azure_pipelines.ap.steps

WaitForClusterSucceeded = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, timeoutInMinutes: int = 60 -> steps.Step {
    script = """
while true; do
  STATE=$(az aks show \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --query "provisioningState" \\
    --output tsv)
  echo "Cluster provisioning state: $STATE"
  if [ "$STATE" = "Succeeded" ]; then
    echo "Cluster is ready."
    break
  elif [ "$STATE" = "Failed" ] || [ "$STATE" = "Canceled" ]; then
    echo "Cluster failed with state: $STATE."
    exit 1
  else
    echo "Provisioning state: $STATE. Retry in 30 seconds"
  fi
  sleep 30
done
"""
    AzCli(serviceConnection, "Wait for cluster to succeed", script, timeoutInMinutes=timeoutInMinutes)
}
