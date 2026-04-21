"""AKS cluster lifecycle management — create, wait, get kubeconfigs, delete."""

import json
from pathlib import Path

from .config import log
from .utils import retry, run


def az_login(msi_client_id: str, subscription_id: str) -> None:
    """Login to Azure and set subscription."""
    if msi_client_id:
        log.info("Logging in to Azure (MSI: %s)...", msi_client_id)
        run(["az", "login", "--identity", "--client-id", msi_client_id])
    else:
        log.info("Skipping MSI login (local mode), using existing az session")
    run(["az", "account", "set", "-s", subscription_id])
    log.info("Azure login OK, subscription: %s", subscription_id)


@retry(max_attempts=3, backoff=30.0)
def create_resource_group(name: str, location: str) -> None:
    """Create an Azure resource group."""
    log.info("Creating resource group %s in %s...", name, location)
    run(["az", "group", "create", "-n", name, "-l", location])


def _get_cluster_state(resource_group: str, name: str) -> str | None:
    """Return the provisioning state of an AKS cluster, or None if it doesn't exist."""
    result = run(
        ["az", "aks", "show", "-g", resource_group, "-n", name,
         "--query", "provisioningState", "-o", "tsv"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@retry(max_attempts=3, backoff=60.0)
def create_cluster(resource_group: str, name: str, location: str,
                   node_count: int, vm_size: str, max_pods: int = 250) -> None:
    """Create an AKS cluster with idempotent retry handling."""
    state = _get_cluster_state(resource_group, name)

    if state == "Succeeded":
        log.info("Cluster %s already exists and is healthy, skipping.", name)
        return

    if state == "Failed":
        log.info("Cluster %s is in Failed state, deleting before retry...", name)
        run(["az", "aks", "delete", "-g", resource_group, "-n", name,
             "--yes", "--no-wait"], check=False)
        run(["az", "aks", "wait", "-g", resource_group, "-n", name,
             "--deleted", "--timeout", "600"], check=False)

    log.info("Creating AKS cluster %s (%d nodes, %s)...", name, node_count, vm_size)
    run([
        "az", "aks", "create",
        "-g", resource_group, "-n", name,
        "-l", location,
        "--node-count", str(node_count),
        "--node-vm-size", vm_size,
        "--max-pods", str(max_pods),
        "--generate-ssh-keys",
        "--no-wait",
    ])


@retry(max_attempts=3, backoff=60.0)
def wait_for_cluster(resource_group: str, name: str, timeout: int = 1200) -> None:
    """Wait for an AKS cluster to be created."""
    log.info("Waiting for cluster %s to be ready (timeout %ds)...", name, timeout)
    run(["az", "aks", "wait", "-g", resource_group, "-n", name,
         "--created", "--timeout", str(timeout)])
    log.info("Cluster %s is ready.", name)


def get_kubeconfig(resource_group: str, name: str, output_path: str) -> None:
    """Download kubeconfig for an AKS cluster."""
    log.info("Getting kubeconfig for %s -> %s", name, output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    run(["az", "aks", "get-credentials",
         "-g", resource_group, "-n", name,
         "--file", output_path, "--overwrite-existing"])


def create_clusters(resource_group: str, cp_cluster: str, dp_cluster: str,
                    location: str, cp_node_count: int, dp_node_count: int,
                    vm_size: str, kubeconfig_dir: str,
                    max_pods: int = 250) -> tuple[str, str]:
    """Create both CP + DP clusters and return kubeconfig paths."""
    create_resource_group(resource_group, location)

    create_cluster(resource_group, cp_cluster, location, cp_node_count, vm_size, max_pods)
    create_cluster(resource_group, dp_cluster, location, dp_node_count, vm_size, max_pods)

    wait_for_cluster(resource_group, cp_cluster)
    wait_for_cluster(resource_group, dp_cluster)

    cp_kubeconfig = str(Path(kubeconfig_dir) / "cp.kubeconfig")
    dp_kubeconfig = str(Path(kubeconfig_dir) / "dp.kubeconfig")
    get_kubeconfig(resource_group, cp_cluster, cp_kubeconfig)
    get_kubeconfig(resource_group, dp_cluster, dp_kubeconfig)

    log.info("Both clusters ready. Kubeconfigs: %s, %s", cp_kubeconfig, dp_kubeconfig)
    return cp_kubeconfig, dp_kubeconfig


@retry(max_attempts=3, backoff=30.0)
def delete_resource_group(name: str) -> None:
    """Delete a resource group (async)."""
    log.info("Deleting resource group %s...", name)
    run(["az", "group", "delete", "-n", name, "--yes", "--no-wait"])
    log.info("Resource group deletion initiated: %s", name)
