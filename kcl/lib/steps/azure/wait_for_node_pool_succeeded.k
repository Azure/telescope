import azure_pipelines.ap.steps

waitForNodePoolScript = lambda cluster: str, resourceGroup: str, subscription: str, poolName: str -> str {
    """
while true; do
  STATE=$(az aks nodepool show \\
    --cluster-name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --name "${poolName}" \\
    --query "provisioningState" \\
    --output tsv)
  echo "Node pool ${poolName} provisioning state: $STATE"
  if [ "$STATE" = "Succeeded" ]; then
    echo "Node pool ${poolName} is ready."
    break
  elif [ "$STATE" = "Failed" ] || [ "$STATE" = "Canceled" ]; then
    echo "Node pool ${poolName} failed with state: $STATE."
    exit 1
  else
    echo "Node pool ${poolName} provisioning state: $STATE. Retry in 30 seconds"
  fi
  sleep 30
done
"""
}

WaitForNodePoolSucceeded = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str -> steps.Step {
    AzCli(
        serviceConnection,
        "Wait for node pool ${poolName} to succeed",
        waitForNodePoolScript(cluster, resourceGroup, subscription, poolName),
    )
}

# WaitForPoolNodesReady waits for a single NodePool to reach
# provisioningState=Succeeded and then have all of its expected nodes Ready
# via kubectl. The caller must have run GetCredentials earlier in the job so
# kubectl is configured.
WaitForPoolNodesReady = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pool: NodePool -> steps.Step {
    script = """
${waitForNodePoolScript(cluster, resourceGroup, subscription, pool.name)}
echo "Waiting for ${pool.count} nodes in pool ${pool.name} to be Ready..."
while true; do
  READY=$(kubectl get nodes --no-headers 2>/dev/null \\
    | awk '$1 ~ /^aks-${pool.name}-/ && $2 == "Ready" {c++} END {print c+0}')
  NOT_READY=$(( ${pool.count} - READY ))
  if [ "$NOT_READY" -le 0 ]; then
    echo "Pool ${pool.name}: all ${pool.count} nodes are Ready."
    break
  fi
  echo "Pool ${pool.name}: $READY / ${pool.count} Ready ($NOT_READY not ready). Retry in 30 seconds"
  sleep 30
done
echo "Node pool ${pool.name} is provisioned and Ready."
"""
    AzCli(serviceConnection, "Wait for node pool ${pool.name} to be ready", script)
}
