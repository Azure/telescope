import azure_pipelines.ap.steps

# NodePool describes a single AKS node pool: a unique pool name, the VM SKU,
# the desired node count, and optional taint/labels
schema NodePool:
    name: str
    sku: str
    count: int
    taintPrefix: str = ""
    labels: str = ""
    maxPods?: int
    vnetSubnetId?: str
    osSKU?: str

# CREATE_NODEPOOL_RETRY_WINDOW_SEC is the maximum time (in seconds) to keep retrying node pool creation when AKS returns OperationNotAllowed.
CREATE_NODEPOOL_RETRY_WINDOW_SEC = 600

CreateNodePool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pool: NodePool, noWait: bool = False -> steps.Step {
    flagDecision = [
        "--node-taints ${pool.taintPrefix}=true:NoSchedule" if pool.taintPrefix else "",
        "--labels \"${pool.labels}\"" if pool.labels else "",
        "--max-pods ${pool.maxPods}" if pool.maxPods else "",
        "--vnet-subnet-id \"${pool.vnetSubnetId}\"" if pool.vnetSubnetId else "",
        "--os-sku ${pool.osSKU}" if pool.osSKU else "",
        "--no-wait" if noWait else "",
    ]
    flags = " \\\n  ".join([f for f in flagDecision if f])
    # Allow retry on OperationNotAllowed — it's observed that AKS can spin up PutExtensionAddonHandler operation in the background that causes transient OperationNotAllowed errors on node pool PUT requests
    script = """
deadline=$(($(date +%s) + ${CREATE_NODEPOOL_RETRY_WINDOW_SEC}))
sleep_between=30
attempt=0
while :; do
  attempt=$((attempt + 1))
  set +e
  output=$(az aks nodepool add \\
    --cluster-name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --name "${pool.name}" \\
    --node-count ${pool.count} \\
    --node-vm-size "${pool.sku}" \\
    --mode User \\
    ${flags} 2>&1)
  rc=$?
  set -e
  echo "$output"
  if [ $rc -eq 0 ]; then
    exit 0
  fi
  case "$output" in
    *OperationNotAllowed*) ;;
    *)
      echo "Non-retriable error (rc=$rc); giving up after attempt $attempt."
      exit $rc
      ;;
  esac
  now=$(date +%s)
  if [ $now -ge $deadline ]; then
    echo "OperationNotAllowed persisted past ${CREATE_NODEPOOL_RETRY_WINDOW_SEC}s retry window ($attempt attempts); giving up."
    exit $rc
  fi
  remaining=$((deadline - now))
  echo "Attempt $attempt got OperationNotAllowed; retrying in $sleep_between seconds ($remaining seconds remain in retry window)."
  sleep $sleep_between
done
"""
    AzCli(serviceConnection, "Create node pool ${pool.name}", script)
}

# PlanNodePools expands a {sku: totalNodes} map into an ordered list of
# NodePool values, one per node pool to create. Each SKU is split into
# ceil(totalNodes / maxNodesPerPool) pools, with the last pool possibly
# smaller. Pool names are assigned globally as workerpool0, workerpool1, ...
PlanNodePools = lambda skuToNodes: {str:int}, maxNodesPerPool: int = 800 -> [NodePool] {
    skuList = [sku for sku in skuToNodes if skuToNodes[sku] > 0]
    skusNested = [
        [sku for i in range((skuToNodes[sku] + maxNodesPerPool - 1) // maxNodesPerPool)]
        for sku in skuList
    ]
    countsNested = [
        [
            maxNodesPerPool if i < (skuToNodes[sku] + maxNodesPerPool - 1) // maxNodesPerPool - 1 else skuToNodes[sku] - i * maxNodesPerPool
            for i in range((skuToNodes[sku] + maxNodesPerPool - 1) // maxNodesPerPool)
        ]
        for sku in skuList
    ]
    skus = sum(skusNested, [])
    counts = sum(countsNested, [])
    [NodePool {
        name = "workerpool${idx}"
        sku = skus[idx]
        count = counts[idx]
    } for idx in range(len(skus))]
}
