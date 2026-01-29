"""
MPI operator installation module.

This module handles the installation of the MPI Operator for distributed workloads.
"""

from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from clients.kubernetes_client import KubernetesClient
from .utils import install_operator

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def install_mpi_operator(
    chart_version: str,
    config_dir: str,
) -> None:
    """
    Install MPI Operator using Helm

    Args:
        chart_version: Specific chart version to install (e.g., "0.5.0")
        config_dir: Directory containing custom configuration files
    """
    install_operator(
        chart_version=chart_version,
        operator_name="mpi-operator",
        config_dir=config_dir,
        namespace="mpi-operator",
        repo_name="v3io-stable",
        repo_url="https://v3io.github.io/helm-charts/stable",
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app.kubernetes.io/name=mpi-operator",
        namespace="mpi-operator",
        operation_timeout_in_minutes=5,
    )
