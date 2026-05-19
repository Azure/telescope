import azure_pipelines.ap.steps

# NodePool describes a single AKS node pool: a unique pool name, the VM SKU, and the desired node count.
schema NodePool:
    name: str
    sku: str
    count: int

CreateNodePool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str, vmSize: str, count: int, taintPrefix: str = "", labels: str = "", noWait: bool = False -> steps.Step {
    flagDecision = [
        "--node-taints ${taintPrefix}=true:NoSchedule" if taintPrefix else "",
        "--labels \"${labels}\"" if labels else "",
        "--no-wait" if noWait else "",
    ]
    flags = " ".join([f for f in flagDecision if f])
    script = """
az aks nodepool add \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${poolName}" \\
  --node-count ${count} \\
  --node-vm-size "${vmSize}" \\
  --mode User \\
  ${flags}
"""
    AzCli(serviceConnection, "Create node pool ${poolName}", script)
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

# CreateNodePools emits one `az aks nodepool add --no-wait` step per NodePool,
# so all pools provision in parallel. Typical usage is to pass the
# [NodePool] returned by PlanNodePools, then pair this with
# WaitForAllWorkerNodesReady (with the same [NodePool]) to gate on completion.
CreateNodePools = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, pools: [NodePool], taintPrefix: str = "", labels: str = "" -> [steps.Step] {
    [
        CreateNodePool(
            serviceConnection,
            cluster,
            resourceGroup,
            subscription,
            entry.name,
            entry.sku,
            entry.count,
            taintPrefix,
            labels,
            True,
        )
        for entry in pools
    ]
}
