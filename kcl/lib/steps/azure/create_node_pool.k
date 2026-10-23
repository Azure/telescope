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

# CREATE_NODEPOOL_RETRY_WINDOW_SEC is the maximum time (in seconds) to keep retrying node pool creation when AKS returns a transient retriable error.
CREATE_NODEPOOL_RETRY_WINDOW_SEC = 600

# Transient errors to retry when creating node pools (separated with '|')
CREATE_NODEPOOL_TRANSIENT_ERRORS = "OperationNotAllowed"

_CREATE_NODE_POOL_FUNCTION = """
create_node_pool() {
  local deadline sleep_between=30 attempt=0 output rc now remaining_retry_seconds
  deadline=$(($(date +%s) + ${CREATE_NODEPOOL_RETRY_WINDOW_SEC}))
  while :; do
    attempt=$((attempt + 1))
    if output=$(az aks nodepool add "$@" 2>&1); then
      rc=0
    else
      rc=$?
    fi
    echo "$output"
    if [ "$rc" -eq 0 ]; then
      return 0
    fi
    if echo "$output" | grep -qiE "${CREATE_NODEPOOL_TRANSIENT_ERRORS}"; then
      now=$(date +%s)
      if [ "$now" -ge "$deadline" ]; then
        echo "Retriable error persisted past ${CREATE_NODEPOOL_RETRY_WINDOW_SEC}s retry window ($attempt attempts); giving up."
        return "$rc"
      fi
      remaining_retry_seconds=$((deadline - now))
      echo "Attempt $attempt matched retriable pattern; retrying in $sleep_between seconds ($remaining_retry_seconds seconds remain in retry window)."
      sleep "$sleep_between"
    else
      echo "Non-retriable error (rc=$rc); giving up after attempt $attempt."
      return "$rc"
    fi
  done
}
"""

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
    script = """
${_CREATE_NODE_POOL_FUNCTION}

create_node_pool \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${pool.name}" \\
  --node-count ${pool.count} \\
  --node-vm-size "${pool.sku}" \\
  --mode User \\
  ${flags}
"""
    AzCli(serviceConnection, "Create node pool ${pool.name}", script)
}

# CreateNodePoolsFromPipelineParameter splits a pipeline-provided node count
# across sequentially created pools.
# totalNodesParameterName must be a full Azure DevOps parameter reference written
# in KCL as "\${{ parameters.total_nodes }}", not a bare parameter name.
# The reference is preserved in the generated script for Azure DevOps to resolve.
# For a node count known during KCL generation, use PlanNodePools and CreateNodePool.
CreateNodePoolsFromPipelineParameter = lambda \
    serviceConnection: str, \
    cluster: str, \
    resourceGroup: str, \
    subscription: str, \
    sku: str, \
    totalNodesParameterName: str, \
    maxNodesPerPool: int = 800, \
    namePrefix: str = "workerpool", \
    vnetSubnetId: str = "", \
    osSKU: str = "" \
    -> steps.Step {
    assert maxNodesPerPool > 0, "maxNodesPerPool must be positive"
    assert namePrefix, "namePrefix must not be empty"

    flagDecision = [
        "--vnet-subnet-id \"${vnetSubnetId}\"" if vnetSubnetId else "",
        "--os-sku ${osSKU}" if osSKU else "",
    ]
    flags = " \\\n      ".join([f for f in flagDecision if f])
    script = """
${_CREATE_NODE_POOL_FUNCTION}

TOTAL_NODES="${totalNodesParameterName}"
MAX_NODES_PER_POOL=${maxNodesPerPool}
# AKS allows up to 100 node pools per cluster, including existing pools.
# https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions#service-quotas-and-limits
# This guard does not account for existing pools; AKS enforces the cluster-wide limit.
MAX_NODE_POOLS=100

if ! [[ "$TOTAL_NODES" =~ ^[1-9][0-9]*$ ]]; then
  echo "Total user nodes must be a positive integer; got '$TOTAL_NODES'."
  exit 1
fi
if [ "$TOTAL_NODES" -gt $((MAX_NODES_PER_POOL * MAX_NODE_POOLS)) ]; then
  echo "Total user nodes cannot exceed $((MAX_NODES_PER_POOL * MAX_NODE_POOLS)); got '$TOTAL_NODES'."
  exit 1
fi

remaining=$TOTAL_NODES
pool_index=0
while [ "$remaining" -gt 0 ]; do
  node_count=$MAX_NODES_PER_POOL
  if [ "$remaining" -lt "$MAX_NODES_PER_POOL" ]; then
    node_count=$remaining
  fi
  pool_name="${namePrefix}$pool_index"
  echo "Creating node pool $pool_name with $node_count nodes."

  create_node_pool \\
    --cluster-name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --name "$pool_name" \\
    --node-count "$node_count" \\
    --node-vm-size "${sku}" \\
    --mode User \\
    ${flags}

  remaining=$((remaining - node_count))
  pool_index=$((pool_index + 1))
done
"""
    AzCli(serviceConnection, "Create node pools from pipeline parameter", script)
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
