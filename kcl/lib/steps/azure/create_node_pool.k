import azure_pipelines.ap.steps

MAX_NODES_PER_POOL = 800

CreateNodePool = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, poolName: str, vmSize: str, count: int, taintPrefix: str = "", labels: str = "", noWait: bool = False -> steps.Step {
    taintFlag = "--node-taints ${taintPrefix}=true:NoSchedule" if taintPrefix else ""
    labelFlag = "--labels \"${labels}\"" if labels else ""
    noWaitFlag = "--no-wait" if noWait else ""
    script = """
az aks nodepool add \\
  --cluster-name "${cluster}" \\
  --resource-group "${resourceGroup}" \\
  --subscription "${subscription}" \\
  --name "${poolName}" \\
  --node-count ${count} \\
  --node-vm-size "${vmSize}" \\
  --mode User \\
  ${taintFlag} \\
  ${labelFlag} \\
  ${noWaitFlag}
"""
    AzCli(serviceConnection, "Create node pool ${poolName}", script)
}

# poolPlan expands a {sku: totalNodes} map into three parallel ordered lists
# (names, skus, counts), one entry per node pool to create. Each SKU is split
# into ceil(totalNodes / MAX_NODES_PER_POOL) pools, with the last pool possibly
# smaller.
poolPlan = lambda skuToNodes: {str:int} -> {str:[any]} {
    skusNested = [
        [sku for i in range((skuToNodes[sku] + MAX_NODES_PER_POOL - 1) // MAX_NODES_PER_POOL)]
        for sku in skuToNodes if skuToNodes[sku] > 0
    ]
    countsNested = [
        [
            MAX_NODES_PER_POOL if i < (skuToNodes[sku] + MAX_NODES_PER_POOL - 1) // MAX_NODES_PER_POOL - 1 else skuToNodes[sku] - i * MAX_NODES_PER_POOL
            for i in range((skuToNodes[sku] + MAX_NODES_PER_POOL - 1) // MAX_NODES_PER_POOL)
        ]
        for sku in skuToNodes if skuToNodes[sku] > 0
    ]
    skus = sum(skusNested, [])
    counts = sum(countsNested, [])
    {
        "names" = ["workerpool${idx}" for idx in range(len(skus))]
        "skus" = skus
        "counts" = counts
    }
}

# CreateNodePools splits each (sku, totalNodes) entry in skuToNodes into one or
# more node pools, each capped at MAX_NODES_PER_POOL nodes (the last pool per
# SKU may be smaller). Every pool is created with --no-wait so they all
# provision in parallel; pair this with WaitForAllWorkerNodesReady to gate on completion.
CreateNodePools = lambda serviceConnection: str, cluster: str, resourceGroup: str, subscription: str, skuToNodes: {str:int}, taintPrefix: str = "", labels: str = "" -> [steps.Step] {
    plan = poolPlan(skuToNodes)
    names = plan["names"]
    skus = plan["skus"]
    counts = plan["counts"]
    [
        CreateNodePool(
            serviceConnection,
            cluster,
            resourceGroup,
            subscription,
            names[idx],
            skus[idx],
            counts[idx],
            taintPrefix,
            labels,
            True,
        )
        for idx in range(len(names))
    ]
}
