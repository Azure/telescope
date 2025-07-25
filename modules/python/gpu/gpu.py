import subprocess
import argparse
from utils.logger_config import get_logger, setup_logging
from clients.kubernetes_client import KubernetesClient

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()

def _wait_for_pods_ready(
    selector: str, namespace: str, timeout: str = "300s"
) -> None:
    """
    Wait for pods to be ready using kubectl wait

    Args:
        selector: Label selector for the pods
        namespace: Namespace where pods exist
        timeout: Timeout string (e.g., "300s", "5m")
    """
    wait_command = [
        "kubectl", "wait", "--for=condition=Ready", "pod",
        f"--selector={selector}",
        f"--namespace={namespace}",
        f"--timeout={timeout}"
    ]

    logger.info(f"Executing: {' '.join(wait_command)}")
    subprocess.run(wait_command, check=True)

def _install_operator(
    chart_version: str,
    operator_name: str,
    config_dir: str,
) -> None:
    """
    Install NVIDIA GPU Network Operator using Helm
    
    Args:
        chart_version: Specific chart version to install
        config_dir: Directory containing custom configuration files
    """
    # Add NVIDIA Helm repository
    logger.info("Adding NVIDIA Helm repository")
    subprocess.run([
        "helm", "repo", "add", "nvidia", "https://helm.ngc.nvidia.com/nvidia"
    ], check=True)
    # Update Helm repositories
    logger.info("Updating Helm repositories")
    subprocess.run(["helm", "repo", "update"], check=True)

    # Build Helm install command
    value_file = f"{config_dir}/gpu/{operator_name}/values.yaml"
    command = [
        "helm", "install", operator_name, f"nvidia/{operator_name}",
        "--create-namespace", "--namespace", operator_name,
        "--version", chart_version,
        "--values", value_file,
        "--atomic"
    ]

    # Execute Helm install
    logger.info(f"Executing: {' '.join(command)}")
    subprocess.run(command, check=True)

def _uninstall_operator(
    operator_name: str,
) -> None:
    """
    Uninstall GPU Network Operator
    
    Args:
        release_name: Helm release name to uninstall (default: gpu-operator)
        namespace: Namespace where the operator is installed (default: gpu-operator)
    """
    logger.info(f"Uninstalling release '{operator_name}' from namespace '{operator_name}'")

    subprocess.run([
        "helm", "uninstall", operator_name, "--namespace", operator_name
    ], check=True)

    logger.info(f"Release '{operator_name}' uninstalled successfully")

def _verify_rdma() -> None:
    """
    Verify RDMA configuration by checking the status of RDMA devices
    """
    mofed_pods = KUBERNETES_CLIENT.get_ready_pods_by_namespace(
        label_selector="nvidia.com/ofed-driver=",
        namespace="network-operator"
    )
    for pod in mofed_pods:
        KUBERNETES_CLIENT.run_pod_exec_command(
            pod_name=pod.metadata.name,
            namespace="network-operator",
            command="ibdev2netdev"
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
    _install_operator(
        chart_version=chart_version,
        operator_name="network-operator",
        config_dir=config_dir
    )
    _wait_for_pods_ready(
        selector="app.kubernetes.io/instance=network-operator",
        namespace="network-operator",
        timeout="300s"
    )

    nfd_install_command = [
        "kubectl", "apply", "-f",
        f"{config_dir}/gpu/network-operator/node-feature-discovery.yaml"
    ]
    logger.info(f"Executing: {' '.join(nfd_install_command)}")
    subprocess.run(nfd_install_command, check=True)
    nic_install_command = [
        "kubectl", "apply", "-f",
        f"{config_dir}/gpu/network-operator/nic-cluster-policy.yaml"
    ]
    logger.info(f"Executing: {' '.join(nic_install_command)}")
    subprocess.run(nic_install_command, check=True)

    _wait_for_pods_ready(
        selector="nvidia.com/ofed-driver=",
        namespace="network-operator",
        timeout="300s"
    )
    _wait_for_pods_ready(
        selector="app=rdma-shared-dp",
        namespace="network-operator",
        timeout="300s"
    )
    _verify_rdma()

def install_gpu_operator(
    chart_version: str,
    config_dir: str,
) -> None:
    """
    Install NVIDIA GPU Operator using Helm
    
    Args:
        chart_version: Specific chart version to install
        config_dir: Directory containing custom configuration files
    """
    _install_operator(
        chart_version=chart_version,
        operator_name="gpu-operator",
        config_dir=config_dir
    )
    _wait_for_pods_ready(
        selector="app.kubernetes.io/managed-by=gpu-operator",
        namespace="gpu-operator",
        timeout="600s"
    )
    _wait_for_pods_ready(
        selector="app.kubernetes.io/component=nvidia-driver",
        namespace="gpu-operator",
        timeout="600s"
    )
    KUBERNETES_CLIENT.wait_for_pods_completed(
        label_selector="app=nvidia-cuda-validator",
        namespace="gpu-operator",
        timeout=600
    )

def install_mpi_operator(
    chart_version: str,
) -> None:
    """
    Install NVIDIA MPI Operator using Helm
    
    Args:
        chart_version: Specific chart version to install
    """
    install_command = [
        "kubectl", "apply", "--server-side", "-f",
        f"https://raw.githubusercontent.com/kubeflow/mpi-operator/{chart_version}/deploy/v2beta1/mpi-operator.yaml"
    ]
    logger.info(f"Executing: {' '.join(install_command)}")
    subprocess.run(install_command, check=True)
    _wait_for_pods_ready(
        selector="app.kubernetes.io/name=mpi-operator",
        namespace="mpi-operator",
        timeout="300s"
    )

def configure(
    network_operator_version: str,
    gpu_operator_version: str,
    mpi_operator_version: str,
    config_dir: str,
) -> None:
    """
    Install all required operators with specified versions and custom configurations

    Args:
        network_operator_version: Version of the network operator
        gpu_operator_version: Version of the GPU operator
        mpi_operator_version: Version of the MPI operator
        config_dir: Directory containing custom configuration files
    """
    install_network_operator(
        chart_version=network_operator_version,
        config_dir=config_dir
    )
    install_gpu_operator(
        chart_version=gpu_operator_version,
        config_dir=config_dir
    )
    install_mpi_operator(
        chart_version=mpi_operator_version
    )

def main():
    """
    Main function to execute the script
    """
    parser = argparse.ArgumentParser(description="GPU and Network Operator Installation Tool")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Configure command to install all operators
    configure_parser = subparsers.add_parser(
        "configure",
        help="Install all required operators (Network, GPU, and MPI)"
    )
    configure_parser.add_argument(
        "--network_operator_version",
        type=str,
        required=True,
        help="Version of the network operator to install"
    )
    configure_parser.add_argument(
        "--gpu_operator_version",
        type=str,
        required=True,
        help="Version of the GPU operator to install"
    )
    configure_parser.add_argument(
        "--mpi_operator_version",
        type=str,
        required=True,
        help="Version of the MPI operator to install"
    )
    configure_parser.add_argument(
        "--config_dir",
        type=str,
        required=True,
        help="Directory containing custom configuration files"
    )

    # Parse arguments
    args = parser.parse_args()

    # Execute based on command
    if args.command == "configure":
        configure(
            network_operator_version=args.network_operator_version,
            gpu_operator_version=args.gpu_operator_version,
            mpi_operator_version=args.mpi_operator_version,
            config_dir=args.config_dir
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
