import azure_pipelines.ap.steps

# waitForNodePoolScript renders a bash snippet that polls a single AKS node
# pool's provisioningState every 30s, exiting 0 on Succeeded and 1 on
# Failed/Canceled. The pool name is expanded at KCL render time so the emitted
# script has no shell parameters.
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

# bash snippet that polls `kubectl get nodes` until expectedCount nodes from the given AKS pool are Ready
waitForPoolNodesReadyScript = lambda poolName: str, expectedCount: int -> str {
    """
echo "Waiting for ${expectedCount} nodes in pool ${poolName} to be Ready..."
while true; do
  READY=$(kubectl get nodes --no-headers 2>/dev/null \\
    | awk '$1 ~ /^aks-${poolName}-/ && $2 == "Ready" {c++} END {print c+0}')
  NOT_READY=$(( ${expectedCount} - READY ))
  if [ "$NOT_READY" -le 0 ]; then
    echo "Pool ${poolName}: all ${expectedCount} nodes are Ready."
    break
  fi
  echo "Pool ${poolName}: $READY / ${expectedCount} Ready ($NOT_READY not ready). Retry in 30 seconds"
  sleep 30
done
"""
}

# Wait for each NodePool in pools to reach provisioningState=Succeeded and then have its
# expected number of nodes Ready via kubectl. The caller must have run
# GetCredentials earlier in the job so kubectl is configured.
WaitForAllWorkerNodesReady = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pools: [NodePool] -> steps.Step {
    waitOnePool = lambda p: NodePool -> str {
        waitForNodePoolScript(cluster, resourceGroup, subscription, p.name) + waitForPoolNodesReadyScript(p.name, p.count)
    }
    perPoolBlocks = "".join([waitOnePool(p) for p in pools])
    script = """
set -euo pipefail
${perPoolBlocks}
echo "All worker node pools are provisioned and Ready."
"""
    AzCli(serviceConnection, "Wait for all worker nodes to be ready", script)
}
