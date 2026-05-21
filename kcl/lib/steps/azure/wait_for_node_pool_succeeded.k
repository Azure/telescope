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
# provisioningState=Succeeded and then have at least readyThreshold of
# expected nodes Ready via kubectl. readyThreshold defaults to 1.0 (all
# nodes). The caller must have run GetCredentials earlier in the job so kubectl
# is configured.
WaitForPoolNodesReady = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pool: NodePool, readyThreshold: float = 1.0 -> steps.Step {
    assert readyThreshold > 0.0 and readyThreshold <= 1.0, "readyThreshold must be in (0.0, 1.0]"
    requiredReady = int(pool.count * readyThreshold + 0.5)
    script = """
${waitForNodePoolScript(cluster, resourceGroup, subscription, pool.name)}
echo "Waiting for at least ${requiredReady} of ${pool.count} nodes in pool ${pool.name} to be Ready..."
while true; do
  READY=$(kubectl get nodes --no-headers 2>/dev/null \\
    | awk '$1 ~ /^aks-${pool.name}-/ && $2 == "Ready" {c++} END {print c+0}')
  if [ "$READY" -ge ${requiredReady} ]; then
    echo "Pool ${pool.name}: $READY / ${pool.count} Ready (>= ${requiredReady} required)."
    break
  fi
  echo "Pool ${pool.name}: $READY / ${pool.count} Ready (need ${requiredReady}). Retry in 30 seconds"
  sleep 30
done
echo "Node pool ${pool.name} is provisioned and Ready."
"""
    AzCli(serviceConnection, "Wait for node pool ${pool.name} to be ready", script)
}
