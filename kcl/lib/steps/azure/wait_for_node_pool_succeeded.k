import azure_pipelines.ap.steps

WaitForNodePoolSucceeded = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str -> steps.Step {
    script = """
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
    AzCli(serviceConnection, "Wait for node pool ${poolName} to succeed", script)
}

# WaitForPoolNodesReady waits until at least readyThreshold of pool.count nodes
# in the given pool are Ready via kubectl. readyThreshold defaults to 1.0 (all
# nodes). Callers are expected to have already gated on
# provisioningState=Succeeded (e.g. via WaitForNodePoolSucceeded) and run
# GetCredentials so kubectl is configured.
WaitForPoolNodesReady = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pool: NodePool, readyThreshold: float = 1.0 -> steps.Step {
    assert readyThreshold > 0.0 and readyThreshold <= 1.0, "readyThreshold must be in (0.0, 1.0]"
    requiredReady = int(pool.count * readyThreshold + 0.5)
    script = """
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
    steps.Bash {
        bash = "set -exo pipefail\n" + script
        displayName = "Wait for pool nodes for ${pool.name} to be ready"
    }
}
