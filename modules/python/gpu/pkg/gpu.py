"""
GPU operator installation and verification module.

This module handles the installation of the NVIDIA GPU Operator.
"""

from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from clients.kubernetes_client import KubernetesClient
from .utils import install_operator

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def _verify_smi() -> None:
    """
    Verify GPU topology by checking nvidia-smi on GPU nodes
    """
    driver_pods = KUBERNETES_CLIENT.get_ready_pods_by_namespace(
        label_selector="app.kubernetes.io/component=nvidia-driver",
        namespace="gpu-operator",
    )
    for pod in driver_pods:
        KUBERNETES_CLIENT.run_pod_exec_command(
            pod_name=pod.metadata.name,
            namespace="gpu-operator",
            command="nvidia-smi",
        )


def install_gpu_operator(
    chart_version: str,
    config_dir: str,
    install_driver: bool,
    enable_nfd: bool,
) -> None:
    """
    Install NVIDIA GPU Operator using Helm

    Args:
        chart_version: Specific chart version to install
        config_dir: Directory containing custom configuration files
        install_driver: Install NVIDIA driver as part of GPU operator installation
        enable_nfd: Enable NVIDIA GPU feature discovery (NFD)
    """
    install_operator(
        chart_version=chart_version,
        operator_name="gpu-operator",
        config_dir=config_dir,
        namespace="gpu-operator",
        extra_args=["--set", f"nfd.enabled={str(enable_nfd).lower()}"],
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app.kubernetes.io/managed-by=gpu-operator",
        namespace="gpu-operator",
        operation_timeout_in_minutes=10,
    )
    if install_driver:
        execute_with_retries(
            KUBERNETES_CLIENT.wait_for_pods_ready,
            label_selector="app.kubernetes.io/component=nvidia-driver",
            namespace="gpu-operator",
            operation_timeout_in_minutes=10,
        )
    if enable_nfd:
        execute_with_retries(
            KUBERNETES_CLIENT.wait_for_pods_ready,
            label_selector="app.kubernetes.io/name=node-feature-discovery",
            namespace="gpu-operator",
            operation_timeout_in_minutes=10,
        )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_completed,
        label_selector="app=nvidia-cuda-validator",
        namespace="gpu-operator",
        timeout=600,
    )
    if install_driver:
        _verify_smi()
