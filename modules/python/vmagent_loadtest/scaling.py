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


@retry(max_attempts=3, backoff=15.0)
def _scale_single_pool(resource_group: str, cluster_name: str, nodepool: str,
                       node_count: int) -> None:
    """Scale one existing nodepool to node_count (skips if already there)."""
    spec = _get_nodepool(resource_group, cluster_name, nodepool)
    if spec is not None and spec.get("count", -1) == node_count:
        log.info("Nodepool '%s' already at %d nodes, skipping scale.", nodepool, node_count)
        return
    log.info("Scaling DP nodepool '%s' to %d nodes...", nodepool, node_count)
    run([
        "az", "aks", "nodepool", "scale",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", nodepool,
        "--node-count", str(node_count),
        "--no-wait",
    ])


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
                            nodepool: str) -> None:
    """Delete the extra fan-out nodepools (<base>2, <base>3, ...) that the
    multi-nodepool scaling created to exceed the AKS per-nodepool cap.

    The base pool (``nodepool``) is left intact — it is provisioned by
    terraform, not by this code. Called at teardown so tiers > 1000 don't
    leave orphaned nodepools burning cores.
    """
    deleted = 0
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
        deleted += 1
    if deleted:
        log.info("Requested deletion of %d fan-out nodepool(s).", deleted)
    else:
        log.info("No fan-out nodepools to delete.")



def wait_for_nodes_ready(kubeconfig: str, expected: int,
                         timeout_minutes: int = 30, poll_interval: int = 30) -> int:
    """Wait until at least `expected` nodes are in Ready state."""
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
        log.info("  nodes: %d/%d Ready", ready_count, expected)
        if ready_count >= expected:
            log.info("All %d nodes are Ready.", expected)
            return ready_count
        time.sleep(poll_interval)
    log.warning("Timed out waiting for %d nodes (got %d)", expected, ready_count)
    return ready_count
