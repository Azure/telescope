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
