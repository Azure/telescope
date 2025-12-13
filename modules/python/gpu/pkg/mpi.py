"""
MPI operator installation module.

This module handles the installation of the MPI Operator for distributed workloads.
"""

from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from clients.kubernetes_client import KubernetesClient

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def install_mpi_operator(
    chart_version: str,
) -> None:
    """
    Install MPI Operator using Helm

    Args:
        chart_version: Specific chart version to install
    """
    mpi_file = f"https://raw.githubusercontent.com/kubeflow/mpi-operator/{chart_version}/deploy/v2beta1/mpi-operator.yaml"
    KUBERNETES_CLIENT.apply_manifest_from_url(mpi_file)
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app.kubernetes.io/name=mpi-operator",
        namespace="mpi-operator",
        operation_timeout_in_minutes=5,
    )
