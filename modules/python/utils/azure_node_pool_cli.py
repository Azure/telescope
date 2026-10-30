"""Azure CLI helpers for AKS node-pool operations."""

import subprocess
import time
from functools import partial

from utils.constants import AzureNodePoolTypeConstants
from utils.logger_config import get_logger
from utils.provisioning_instrumentation import TIMEOUT_SECONDS, begin_create_or_update_with_retry

logger = get_logger(__name__)


def get_node_pool_scale_state(node_pool, node_pool_type):
    """Return current node count and VM size for VMSS or VirtualMachines pools."""
    if node_pool_type != AzureNodePoolTypeConstants.VIRTUAL_MACHINES:
        return node_pool.count, node_pool.vm_size

    profile = node_pool.virtual_machines_profile
    scale = profile.get("scale") if isinstance(profile, dict) else profile.scale
    manual = scale.get("manual") if isinstance(scale, dict) else scale.manual
    if not manual:
        raise ValueError("VirtualMachines node pool has no manual scale profile")
    if len(manual) != 1:
        raise ValueError(
            "VirtualMachines node pools with multiple manual scale profiles "
            "are not supported"
        )

    def read(entry, field):
        return entry.get(field) if isinstance(entry, dict) else getattr(entry, field)

    count = read(manual[0], "count")
    if count is None:
        raise ValueError("VirtualMachines manual scale profile has no node count")
    return count, read(manual[0], "size")


def build_add_virtual_machines_command(
    resource_group, cluster_name, node_pool_name, node_count, vm_size
):
    """Build the Azure CLI command that creates a VirtualMachines node pool."""
    return [
        "az", "aks", "nodepool", "add",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", node_pool_name,
        "--node-count", str(node_count),
        "--vm-sizes", vm_size,
        "--vm-set-type", AzureNodePoolTypeConstants.VIRTUAL_MACHINES,
        "--mode", "User",
        "--node-osdisk-type", "Managed",
    ]


def build_scale_virtual_machines_command(
    resource_group, cluster_name, node_pool_name, node_count
):
    """Build the Azure CLI command that scales a VirtualMachines node pool."""
    return [
        "az", "aks", "nodepool", "scale",
        "--resource-group", resource_group,
        "--cluster-name", cluster_name,
        "--name", node_pool_name,
        "--node-count", str(node_count),
    ]


def run_node_pool_cli(
    cmd,
    node_pool_name,
    action,
    retries=10,
    retry_wait=30,
    timeout=TIMEOUT_SECONDS,
):
    """Run an az command; return (successful attempt start, retry_occurred)."""
    retry_occurred = False
    for attempt in range(retries):
        request_started_at = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            error.request_started_at = request_started_at
            raise
        if result.returncode == 0:
            return request_started_at, retry_occurred
        detail = " | ".join(
            line
            for line in (result.stdout + result.stderr).splitlines()
            if line.strip()
        )
        in_progress = any(code in detail for code in ("OperationNotAllowed", "EtagMismatch"))
        if in_progress and attempt < retries - 1:
            retry_occurred = True
            logger.warning(
                "Cluster has an in-progress operation, retrying %s for %s in %ss "
                "(attempt %s/%s)",
                action,
                node_pool_name,
                retry_wait,
                attempt + 1,
                retries,
            )
            time.sleep(retry_wait)
            continue
        error = RuntimeError(
            f"az aks nodepool {action} failed for {node_pool_name} "
            f"(rc={result.returncode}): {detail}"
        )
        error.request_started_at = time.time() if in_progress else request_started_at
        raise error
    raise RuntimeError(f"Node pool {node_pool_name} exhausted {retries} {action} retries")


def create_virtual_machines_node_pool(
    resource_group, cluster_name, node_pool_name, node_count, vm_size,
    timeout=TIMEOUT_SECONDS,
):
    """Create a pool and return its successful attempt timestamp and retry flag."""
    command = build_add_virtual_machines_command(
        resource_group, cluster_name, node_pool_name, node_count, vm_size
    )
    return run_node_pool_cli(command, node_pool_name, "add", timeout=timeout)


def scale_virtual_machines_node_pool(
    resource_group, cluster_name, node_pool_name, node_count,
    timeout=TIMEOUT_SECONDS,
):
    """Scale a pool and return its successful attempt timestamp and retry flag."""
    command = build_scale_virtual_machines_command(
        resource_group, cluster_name, node_pool_name, node_count
    )
    return run_node_pool_cli(command, node_pool_name, "scale", timeout=timeout)


def prepare_create_operation(
    parameters,
    node_pool_type,
    gpu_node_pool,
    resource_group,
    cluster_name,
    node_pool_name,
    node_count,
    vm_size,
    aks_sdk_client,
    label="",
    timeout=TIMEOUT_SECONDS,
):
    """Return a node-pool create callable for the requested pool type."""
    if node_pool_type != AzureNodePoolTypeConstants.VIRTUAL_MACHINES:
        sdk_parameters = {
            **parameters,
            "count": node_count,
            "vm_size": vm_size,
        }
        return partial(
            begin_create_or_update_with_retry,
            aks_sdk_client,
            resource_group,
            cluster_name,
            node_pool_name,
            sdk_parameters,
            label=label,
            timeout=timeout,
        )
    if gpu_node_pool:
        raise ValueError("GPU node pools with type VirtualMachines are not supported")
    return partial(
        create_virtual_machines_node_pool,
        resource_group,
        cluster_name,
        node_pool_name,
        node_count,
        vm_size,
        timeout=timeout,
    )


def prepare_scale_operation(
    node_pool,
    node_pool_type,
    resource_group,
    cluster_name,
    node_pool_name,
    node_count,
    aks_sdk_client,
    label="",
    timeout=TIMEOUT_SECONDS,
):
    """Return a node-pool scale callable for the requested pool type."""
    if node_pool_type != AzureNodePoolTypeConstants.VIRTUAL_MACHINES:
        node_pool.count = node_count
        return partial(
            begin_create_or_update_with_retry,
            aks_sdk_client,
            resource_group,
            cluster_name,
            node_pool_name,
            node_pool,
            label=label,
            timeout=timeout,
        )
    return partial(
        scale_virtual_machines_node_pool,
        resource_group,
        cluster_name,
        node_pool_name,
        node_count,
        timeout=timeout,
    )


def add_managed_gpu_node_pool(
    resource_group,
    node_pool_name,
    cluster_name,
    vm_size,
    node_count,
    gpu_instance_profile=None,
    gpu_mig_strategy=None,
):
    """Create a fully managed GPU node pool through the aks-preview CLI."""
    subprocess.run(
        [
            "az",
            "extension",
            "add",
            "--name",
            "aks-preview",
            "--upgrade",
            "--allow-preview",
            "true",
            "--yes",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    cmd = [
        "az",
        "aks",
        "nodepool",
        "add",
        "--resource-group",
        resource_group,
        "--cluster-name",
        cluster_name,
        "--name",
        node_pool_name,
        "--node-count",
        str(node_count),
        "--node-vm-size",
        vm_size,
        "--mode",
        "User",
        "--node-osdisk-type",
        "Managed",
        "--labels",
        "gpu=true",
        "--enable-managed-gpu",
        "true",
    ]
    if gpu_instance_profile:
        cmd += ["--gpu-instance-profile", gpu_instance_profile]
    if gpu_mig_strategy:
        cmd += ["--gpu-mig-strategy", gpu_mig_strategy]

    logger.info("Running: %s", " ".join(cmd))
    retries = 10
    retry_wait = 30
    for attempt in range(retries):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            break
        detail = " | ".join(
            line
            for line in (result.stdout + result.stderr).splitlines()
            if line.strip()
        )
        if "OperationNotAllowed" in detail and attempt < retries - 1:
            logger.warning(
                "Cluster has an in-progress operation, retrying in %ss "
                "(attempt %s/%s)",
                retry_wait,
                attempt + 1,
                retries,
            )
            time.sleep(retry_wait)
            continue
        raise RuntimeError(
            f"az aks nodepool add failed (rc={result.returncode}): {detail}"
        )
    logger.info("az aks nodepool add succeeded for '%s'", node_pool_name)
