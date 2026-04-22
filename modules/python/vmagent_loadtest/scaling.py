"""AKS node scaling helpers."""

import json
import time

from .config import log
from .utils import kubectl, retry, run


@retry(max_attempts=3, backoff=15.0)
def scale_dp_nodepool(resource_group: str, cluster_name: str, nodepool: str,
                      node_count: int, timeout_minutes: int = 30) -> None:
    """Scale the DP cluster nodepool to the desired node count via az CLI."""
    # Check current count to avoid "same count" error
    result = run([
        "az", "aks", "nodepool", "show",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", nodepool,
        "-o", "json",
    ], check=False)
    if result.returncode == 0:
        current = json.loads(result.stdout).get("count", 0)
        if current == node_count:
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
    log.info("Scale request submitted, waiting for nodes to be Ready...")


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
