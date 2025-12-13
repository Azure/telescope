"""
EFA (Elastic Fabric Adapter) operator installation module.

This module handles the installation of AWS EFA device plugin for EKS clusters
and provides helper functions for EFA resource management.
"""

from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from utils.constants import UrlConstants
from clients.kubernetes_client import KubernetesClient
from .utils import install_operator

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def install_efa_operator(
    config_dir: str,
    version: str,
) -> None:
    """Install the EFA device plugin for EKS clusters.

    Args:
        config_dir: Directory containing custom configuration files
        version: Version of the EFA device plugin to install
    """
    install_operator(
        chart_version=version,
        operator_name="aws-efa-k8s-device-plugin",
        config_dir=config_dir,
        namespace="kube-system",
        repo_name="aws",
        repo_url=UrlConstants.EKS_CHARTS_REPO_URL,
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="name=aws-efa-k8s-device-plugin",
        namespace="kube-system",
        operation_timeout_in_minutes=10,
    )


def get_efa_allocatable() -> int:
    """
    Get the allocatable efa resources from the EKS nodes,
    assuming each node has the same amount of efa allocatable.

    Returns:
        int: The number of allocatable EFA resources.
    """
    nodes = KUBERNETES_CLIENT.get_nodes(label_selector="nvidia.com/gpu.present=true")
    if len(nodes) == 0:
        raise RuntimeError("No GPU nodes found in the cluster")

    efa_allocatable = int(nodes[0].status.allocatable.get("vpc.amazonaws.com/efa", 0))
    if efa_allocatable <= 0:
        raise RuntimeError("No allocatable EFA resources found on the GPU nodes")

    return efa_allocatable
