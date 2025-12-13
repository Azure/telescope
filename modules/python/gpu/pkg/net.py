"""
Network operator installation and verification module.

This module handles the installation of the NVIDIA Network Operator and RDMA verification.
"""

from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from clients.kubernetes_client import KubernetesClient
from .utils import install_operator

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def _verify_rdma() -> None:
    """
    Verify RDMA configuration by checking the status of RDMA devices
    """
    mofed_pods = KUBERNETES_CLIENT.get_ready_pods_by_namespace(
        label_selector="nvidia.com/ofed-driver=", namespace="network-operator"
    )
    for pod in mofed_pods:
        KUBERNETES_CLIENT.run_pod_exec_command(
            pod_name=pod.metadata.name,
            namespace="network-operator",
            command="ibdev2netdev",
        )


def install_network_operator(
    chart_version: str,
    config_dir: str,
) -> None:
    """
    Install NVIDIA Network Operator using Helm

    Args:
        chart_version: Specific chart version to install
        config_dir: Directory containing custom configuration files
    """
    install_operator(
        chart_version=chart_version,
        operator_name="network-operator",
        config_dir=config_dir,
        namespace="network-operator",
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app.kubernetes.io/instance=network-operator",
        namespace="network-operator",
        operation_timeout_in_minutes=5,
    )

    nfd_file = f"{config_dir}/net/nfd-network-rule.yaml"
    KUBERNETES_CLIENT.apply_manifest_from_file(nfd_file)
    nic_file = f"{config_dir}/net/nic-cluster-policy.yaml"
    KUBERNETES_CLIENT.apply_manifest_from_file(nic_file)
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="nvidia.com/ofed-driver=",
        namespace="network-operator",
        operation_timeout_in_minutes=5,
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app=sriovdp",
        namespace="network-operator",
        operation_timeout_in_minutes=5,
    )
    _verify_rdma()
