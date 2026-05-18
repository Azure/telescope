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

# WaitForAllWorkerNodesReady waits for every pool in poolToNodes (a map of
# poolName -> expectedNodeCount) to reach provisioningState=Succeeded, then
# waits for the matching total number of worker nodes to be Ready via kubectl.
WaitForAllWorkerNodesReady = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolToNodes: {str:int} -> steps.Step {
    poolNames = [name for name in poolToNodes]
    expectedTotal = sum([poolToNodes[name] for name in poolNames], 0)
    # Regex alternation of "aks-<pool>-" prefixes, e.g. "^aks-(workerpool0|workerpool1)-".
    poolPrefixRegex = "^aks-(" + "|".join(poolNames) + ")-"
    script = """
set -euo pipefail

# Wait for all node pools to reach provisioningState=Succeeded
${"".join([waitForNodePoolScript(cluster, resourceGroup, subscription, name) for name in poolNames])}

echo "All node pools provisioned. Waiting for ${expectedTotal} worker nodes to be Ready..."
while true; do
  # AKS node names follow the pattern aks-<poolname>-..., so filter on the
  # configured pool prefixes to count only nodes from the requested pools.
  READY=$(kubectl get nodes --no-headers 2>/dev/null \\
    | awk '$1 ~ /${poolPrefixRegex}/ && $2 == "Ready" {c++} END {print c+0}')
  echo "Ready worker nodes: $READY / ${expectedTotal}"
  if [ "$READY" -ge "${expectedTotal}" ]; then
    echo "All worker nodes are Ready."
    break
  fi
  sleep 30
done
"""
    AzCli(serviceConnection, "Wait for all worker nodes to be ready", script)
}
