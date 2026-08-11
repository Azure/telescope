"""AKS node scaling helpers."""

import json
import math
import time

from .config import log, MAX_NODES_PER_POOL
from .utils import kubectl, retry, run


def _pool_name(base: str, index: int) -> str:
    """Nodepool name for the Nth pool: base, base2, base3, ..."""
    return base if index == 0 else f"{base}{index + 1}"


def _plan_pools(node_count: int) -> list[int]:
    """Distribute node_count across pools of <= MAX_NODES_PER_POOL.

    Fills each pool to the cap, remainder in the last pool.
    e.g. 2000 -> [1000, 1000]; 1500 -> [1000, 500]; 5000 -> [1000]*5.
    """
    if node_count <= 0:
        return []
    num_pools = math.ceil(node_count / MAX_NODES_PER_POOL)
    counts = []
    remaining = node_count
    for _ in range(num_pools):
        take = min(MAX_NODES_PER_POOL, remaining)
        counts.append(take)
        remaining -= take
    return counts


def _get_nodepool(resource_group: str, cluster_name: str, nodepool: str) -> dict | None:
    result = run([
        "az", "aks", "nodepool", "show",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", nodepool,
        "-o", "json",
    ], check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def _create_nodepool_like(resource_group: str, cluster_name: str, nodepool: str,
                          base_spec: dict, node_count: int) -> None:
    """Create a new user nodepool cloning the base pool's key placement fields."""
    log.info("Creating nodepool '%s' (%d nodes, cloned from base spec)...", nodepool, node_count)
    args = [
        "az", "aks", "nodepool", "add",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", nodepool,
        "--mode", "User",
        "--node-count", str(node_count),
        "--no-wait",
    ]
    # Clone placement-relevant fields so nodes land in the same VNet/VM family.
    if base_spec.get("vmSize"):
        args += ["--node-vm-size", base_spec["vmSize"]]
    if base_spec.get("osType"):
        args += ["--os-type", base_spec["osType"]]
    if base_spec.get("osSku"):
        args += ["--os-sku", base_spec["osSku"]]
    if base_spec.get("vnetSubnetId"):
        args += ["--vnet-subnet-id", base_spec["vnetSubnetId"]]
    if base_spec.get("maxPods"):
        args += ["--max-pods", str(base_spec["maxPods"])]
    run(args)


def _wait_for_nodepool_idle(resource_group: str, cluster_name: str, nodepool: str,
                            timeout_minutes: int = 15, poll_interval: int = 15) -> None:
    """Wait until `nodepool` has no in-progress scale/update operation.

    AKS allows only one operation per nodepool at a time; issuing a new
    scale while one is still in flight is rejected outright
    (OperationNotAllowed). This matters most after a ramp retry: the
    previous attempt's --no-wait scale call may still be running on
    Azure's side even though our own script gave up waiting on it.
    """
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        spec = _get_nodepool(resource_group, cluster_name, nodepool)
        if spec is None:
            return  # pool doesn't exist yet -- nothing to wait on
        state = spec.get("provisioningState", "")
        if state not in ("Scaling", "Updating", "Creating"):
            return
        log.info("  nodepool '%s' still %s, waiting for it to settle before scaling...",
                 nodepool, state)
        time.sleep(poll_interval)
    log.warning("Timed out waiting for nodepool '%s' to become idle (still in progress)", nodepool)


@retry(max_attempts=3, backoff=15.0)
def _scale_single_pool(resource_group: str, cluster_name: str, nodepool: str,
                       node_count: int) -> None:
    """Scale one existing nodepool to node_count (skips if already there)."""
    _wait_for_nodepool_idle(resource_group, cluster_name, nodepool)
    spec = _get_nodepool(resource_group, cluster_name, nodepool)
    if spec is not None and spec.get("count", -1) == node_count:
        log.info("Nodepool '%s' already at %d nodes, skipping scale.", nodepool, node_count)
        return
    log.info("Scaling nodepool '%s' to %d nodes...", nodepool, node_count)
    run([
        "az", "aks", "nodepool", "scale",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", nodepool,
        "--node-count", str(node_count),
        "--no-wait",
    ])


def scale_cp_nodepool(resource_group: str, cp_cluster_name: str, nodepool: str,
                      node_count: int) -> None:
    """Scale the CP cluster's node pool to `node_count` (single pool, no
    fan-out -- CP node counts stay small, well under the AKS per-pool cap
    even at the largest tiers). Load-based sizing lives in
    config.compute_cp_nodes_needed(); this just applies it.
    """
    _scale_single_pool(resource_group, cp_cluster_name, nodepool, node_count)


def scale_dp_nodepool(resource_group: str, cluster_name: str, nodepool: str,
                      node_count: int, timeout_minutes: int = 30) -> None:
    """Scale the DP dataplane to node_count, fanning out across multiple
    nodepools when node_count exceeds the AKS per-nodepool cap.

    Pools are named <base>, <base>2, <base>3, ... Extra pools left over from a
    previous larger tier are scaled down to 0 so cores are freed.
    """
    plan = _plan_pools(node_count)
    base_spec = _get_nodepool(resource_group, cluster_name, nodepool)
    if base_spec is None:
        raise RuntimeError(f"Base nodepool '{nodepool}' not found in {cluster_name}")

    if len(plan) > 1:
        log.info("Tier needs %d nodes > %d/pool → fanning across %d nodepools: %s",
                 node_count, MAX_NODES_PER_POOL, len(plan),
                 ", ".join(f"{_pool_name(nodepool, i)}={c}" for i, c in enumerate(plan)))

    # Scale (creating as needed) each pool in the plan.
    for i, count in enumerate(plan):
        name = _pool_name(nodepool, i)
        if i == 0:
            _scale_single_pool(resource_group, cluster_name, name, count)
        else:
            spec = _get_nodepool(resource_group, cluster_name, name)
            if spec is None:
                _create_nodepool_like(resource_group, cluster_name, name, base_spec, count)
            else:
                _scale_single_pool(resource_group, cluster_name, name, count)

    # Scale down any leftover pools beyond the current plan (previous larger tier).
    idx = len(plan)
    while True:
        name = _pool_name(nodepool, idx)
        spec = _get_nodepool(resource_group, cluster_name, name)
        if spec is None:
            break
        if spec.get("count", 0) != 0:
            log.info("Scaling down leftover nodepool '%s' to 0...", name)
            _scale_single_pool(resource_group, cluster_name, name, 0)
        idx += 1

    log.info("Scale requests submitted, waiting for nodes to be Ready...")


def delete_fanout_nodepools(resource_group: str, cluster_name: str,
                            nodepool: str) -> list[str]:
    """Delete the extra fan-out nodepools (<base>2, <base>3, ...) that the
    multi-nodepool scaling created to exceed the AKS per-nodepool cap.

    The base pool (``nodepool``) is left intact — it is provisioned by
    terraform, not by this code. Called at teardown so tiers > 1000 don't
    leave orphaned nodepools burning cores. Returns the names deleted (each
    fired with --no-wait -- caller decides whether/how long to wait for
    them to actually finish).
    """
    deleted = []
    for idx in range(1, 16):  # base2 .. base16 (covers well past 5k)
        name = _pool_name(nodepool, idx)
        if _get_nodepool(resource_group, cluster_name, name) is None:
            continue
        log.info("Deleting fan-out nodepool '%s'...", name)
        run([
            "az", "aks", "nodepool", "delete",
            "--resource-group", resource_group,
            "--cluster-name", cluster_name,
            "--name", name,
            "--no-wait",
        ], check=False)
        deleted.append(name)
    if deleted:
        log.info("Requested deletion of %d fan-out nodepool(s).", len(deleted))
    else:
        log.info("No fan-out nodepools to delete.")
    return deleted


def scale_down_for_teardown(resource_group: str, dp_cluster_name: str, nodepool: str,
                            cp_cluster_name: str = "", cp_nodepool: str = "",
                            wait_minutes: int = 10) -> None:
    """Delete the fan-out nodepools this code created (dataplane2, ...),
    then wait for EVERY nodepool this code touched to settle out of any
    in-flight operation before the pipeline's terraform destroy /
    `az group delete` step.

    The base DP pool and the CP `controlplane` pool are both provisioned by
    terraform and are NOT resized here -- they get torn down as part of
    normal cluster deletion regardless of node count. But the ramp's own
    last scale-up can still be "Scaling" on Azure's side even after
    wait_for_nodes_ready() returns: the final-tier tolerance_pct margin
    means kubectl can report nodes Ready while Azure is still finishing the
    last few VMs. Handing off to terraform destroy while any nodepool is
    still mid-operation risks the same 'OperationNotAllowed: in-progress
    operation' conflict seen with scale requests -- so every pool this code
    could have touched (base DP pool, fan-out pools, CP pool) is waited on
    here, not just the ones actually deleted.
    """
    if not (resource_group and dp_cluster_name):
        return
    try:
        deleted_names = delete_fanout_nodepools(resource_group, dp_cluster_name, nodepool)
    except Exception as e:
        log.warning("Fan-out nodepool cleanup before teardown failed (non-fatal): %s", e)
        deleted_names = []

    pools = [(dp_cluster_name, nodepool)] + [(dp_cluster_name, n) for n in deleted_names]
    if cp_cluster_name and cp_nodepool:
        pools.append((cp_cluster_name, cp_nodepool))

    remaining = list(pools)
    deadline = time.time() + wait_minutes * 60
    while remaining and time.time() < deadline:
        still_busy = []
        for cluster, pool in remaining:
            spec = _get_nodepool(resource_group, cluster, pool)
            if spec is not None and spec.get("provisioningState") == "Scaling":
                still_busy.append((cluster, pool))
        remaining = still_busy
        if not remaining:
            break
        log.info("  waiting for nodepool(s) %s to settle before teardown...",
                 [p for _, p in remaining])
        time.sleep(20)
    if remaining:
        log.warning("Nodepool(s) %s still scaling after %dm — proceeding to teardown anyway.",
                   [p for _, p in remaining], wait_minutes)
    else:
        log.info("All nodepools settled — safe to proceed to teardown.")



def wait_for_nodes_ready(kubeconfig: str, expected: int,
                         timeout_minutes: int = 30, poll_interval: int = 30,
                         tolerance_pct: float = 0.0) -> int:
    """Wait until at least `expected` nodes (minus `tolerance_pct` margin)
    are in Ready state.

    `tolerance_pct` defaults to 0 (exact match) -- intermediate ramp tiers
    need their real node count for reproducible per-tier data. Callers pass
    a margin (e.g. 0.02) only when scaling to the ramp's FINAL tier, where
    a handful of stragglers at the tail of a large climb (e.g. the last 1-2%
    of 2000 nodes) can lag well behind the rest with no useful signal on
    when they'll actually join.
    """
    min_required = max(1, math.ceil(expected * (1 - tolerance_pct)))
    deadline = time.time() + timeout_minutes * 60
    ready_count = 0
    while time.time() < deadline:
        result = kubectl(
            kubeconfig, "get", "nodes", "--no-headers",
            "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status",
            check=False,
        )
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        ready_count = sum(1 for l in lines if "Ready" in l and "True" in l)
        log.info("  nodes: %d/%d Ready (accepting >= %d)", ready_count, expected, min_required)
        if ready_count >= min_required:
            log.info("%d/%d nodes are Ready (within %.0f%% margin).",
                     ready_count, expected, tolerance_pct * 100)
            return ready_count
        time.sleep(poll_interval)
    log.warning("Timed out waiting for %d nodes (got %d)", expected, ready_count)
    return ready_count
