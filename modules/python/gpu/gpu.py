import subprocess
import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any
import yaml
import requests
from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from utils.common import str2bool
from utils.constants import UrlConstants
from clients.kubernetes_client import KubernetesClient, client

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def _install_operator(
    chart_version: str,
    operator_name: str,
    config_dir: str,
    namespace: str,
    repo_name: str = "nvidia",
    repo_url: str = UrlConstants.NVIDIA_HELM_REPO_URL,
    extra_args: list = None,
) -> None:
    """
    Install NVIDIA GPU Network Operator using Helm

    Args:
        chart_version: Specific chart version to install
        config_dir: Directory containing custom configuration files
        repo_name: Helm repository name
        repo_url: Helm repository URL
        namespace: Kubernetes namespace
        operator_name: Name of the operator
        extra_args: Optional list of extra arguments to pass to helm install (e.g., ['--set', 'key=value'])
    """
    # Add Helm repository
    logger.info(f"Adding Helm repository: {repo_name} ({repo_url})")
    subprocess.run(
        ["helm", "repo", "add", repo_name, repo_url],
        check=True,
    )
    # Update Helm repositories
    logger.info("Updating Helm repositories")
    subprocess.run(["helm", "repo", "update"], check=True)

    # Build Helm install command
    value_file = f"{config_dir}/{operator_name}/values.yaml"
    command = [
        "helm",
        "install",
        operator_name,
        f"{repo_name}/{operator_name}",
        "--create-namespace",
        "--namespace",
        namespace,
        "--version",
        chart_version,
        "--atomic",
    ]

    # Add values file if it exists
    if os.path.exists(value_file):
        command.extend(["--values", value_file])
        logger.info(f"Using values file: {value_file}")
    else:
        logger.info(
            f"Values file not found: {value_file}, proceeding without custom values"
        )

    # Add extra arguments if provided
    if extra_args:
        command.extend(extra_args)
        logger.info(f"Adding extra arguments: {' '.join(extra_args)}")

    # Execute Helm install
    logger.info(f"Executing: {' '.join(command)}")
    subprocess.run(command, check=True)


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
    _install_operator(
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

    nfd_file = f"{config_dir}/network-operator/node-feature-discovery.yaml"
    KUBERNETES_CLIENT.apply_manifest_from_file(nfd_file)
    nic_file = f"{config_dir}/network-operator/nic-cluster-policy.yaml"
    KUBERNETES_CLIENT.apply_manifest_from_file(nic_file)
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="nvidia.com/ofed-driver=",
        namespace="network-operator",
        operation_timeout_in_minutes=5,
    )
    execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_ready,
        label_selector="app=rdma-shared-dp",
        namespace="network-operator",
        operation_timeout_in_minutes=5,
    )
    _verify_rdma()


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
    """
    _install_operator(
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


def install_mpi_operator(
    chart_version: str,
) -> None:
    """
    Install NVIDIA MPI Operator using Helm

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


def configure(
    network_operator_version: str,
    gpu_operator_version: str,
    gpu_install_driver: bool,
    gpu_enable_nfd: bool,
    mpi_operator_version: str,
    efa_operator_version: str,
    config_dir: str,
) -> None:
    """
    Install operators with specified versions and custom configurations

    Args:
        network_operator_version: Version of the network operator
        gpu_operator_version: Version of the GPU operator
        mpi_operator_version: Version of the MPI operator
        config_dir: Directory containing custom configuration files
    """
    if efa_operator_version:
        install_efa_operator(
            config_dir=config_dir,
            version=efa_operator_version,
        )
    if network_operator_version:
        install_network_operator(
            chart_version=network_operator_version, config_dir=config_dir
        )
    if gpu_operator_version:
        install_gpu_operator(
            chart_version=gpu_operator_version,
            config_dir=config_dir,
            install_driver=gpu_install_driver,
            enable_nfd=gpu_enable_nfd,
        )
    if mpi_operator_version:
        install_mpi_operator(chart_version=mpi_operator_version)


def _create_topology_configmap(
    vm_size: str,
) -> None:
    """
    Create a ConfigMap for the topology XML file

    Args:
        vm_size: Type of the machine (e.g., "ndv4", "ndv5")
    """
    # Download topology file from GitHub
    topology_url = f"https://raw.githubusercontent.com/Azure/azhpc-images/master/topology/{vm_size}-topo.xml"

    logger.info(f"Downloading topology file from: {topology_url}")

    try:
        response = requests.get(topology_url, timeout=30)
        response.raise_for_status()
        topology_content = response.text

        # Get Kubernetes API client
        v1_api = KUBERNETES_CLIENT.get_api_client()

        # Create ConfigMap
        configmap_name = "nvidia-topology"
        logger.info(f"Creating ConfigMap from content:\n{topology_content}")
        configmap = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=configmap_name),
            data={"topo.xml": topology_content},
        )
        v1_api.create_namespaced_config_map(namespace="default", body=configmap)
        logger.info(f"ConfigMap '{configmap_name}' created successfully")

    except requests.RequestException as e:
        logger.error(f"Failed to download topology file: {str(e)}")
        raise
    except client.ApiException as e:
        logger.error(f"Failed to create ConfigMap: {str(e)}")
        raise


def install_efa_operator(
    config_dir: str,
    version: str,
) -> None:
    """Install the EFA device plugin for EKS clusters.
    Args:
        config_dir: Directory containing custom configuration files
        version: Version of the EFA device plugin to install
    """
    _install_operator(
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


def _get_gpu_node_count_and_allocatable() -> tuple[int, int]:
    """
    Get the number of GPU nodes and the allocatable GPU resource per node, assuming each node has the same amount of GPU allocatable.

    Returns:
        tuple[int, int]: A tuple containing the number of GPU nodes and the allocatable GPU resources per node.
    """
    nodes = KUBERNETES_CLIENT.get_nodes(label_selector="nvidia.com/gpu.present=true")
    if len(nodes) == 0:
        raise RuntimeError("No GPU nodes found in the cluster")
    gpu_node_count = len(nodes)

    gpu_allocatable = int(nodes[0].status.allocatable.get("nvidia.com/gpu", 0))
    if gpu_allocatable <= 0:
        raise RuntimeError("No allocatable GPU resources found on the GPU nodes")

    return gpu_node_count, gpu_allocatable


def _get_efa_allocatable() -> int:
    """
    Get the allocatable efa resources from the EKS nodes, assuming each node has the same amount of efa allocatable.

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


def execute(
    provider: str,
    config_dir: str,
    result_dir: str,
    vm_size: str = "",
):
    """
    Execute nccl-tests

    Args:
        provider: Cloud provider (e.g., "azure", "aws")
        config_dir: Directory containing custom configuration files
        result_dir:
        vm_size: Type of the machine (e.g., "ndv4", "ndv5")
    """
    gpu_node_count, gpu_allocatable = _get_gpu_node_count_and_allocatable()
    replacements = {
        "slots_per_worker": gpu_allocatable,
        "number_of_processes": gpu_node_count * gpu_allocatable,
        "replicas": gpu_node_count,
        "gpu_allocatable": gpu_allocatable,
    }
    if provider.lower() == "azure":
        _create_topology_configmap(vm_size=vm_size)

    if provider.lower() == "aws":
        efa_allocatable = _get_efa_allocatable()
        replacements["efa_allocatable"] = efa_allocatable

    nccl_file = f"{config_dir}/nccl-tests/{provider}-mpijob.yaml"
    logger.info(f"Running nccl-tests with {replacements} using {nccl_file}")
    nccl_template = KUBERNETES_CLIENT.create_template(nccl_file, replacements)
    nccl_dict = yaml.safe_load(nccl_template)
    KUBERNETES_CLIENT.apply_manifest_from_file(manifest_dict=nccl_dict)
    pods = execute_with_retries(
        KUBERNETES_CLIENT.wait_for_pods_completed,
        label_selector="component=launcher",
        pod_count=1,
    )
    pod_name = pods[0].metadata.name
    raw_logs = KUBERNETES_CLIENT.get_pod_logs(pod_name)
    logs = raw_logs.decode("utf-8")
    logger.info(f"Getting logs for pod {pod_name}:\n{logs}")
    result_path = f"{result_dir}/raw.log"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(logs)
    logger.info(f"Results saved to {result_path}")


def _parse_nccl_test_results(log_file_path: str) -> Dict[str, Any]:
    """
    Parse NCCL test results from log file into structured JSON format

    Args:
        log_file_path: Path to the NCCL test log file

    Returns:
        Dictionary containing parsed test results
    """
    result = {
        "test_info": {},
        "devices": [],
        "performance_data": {"out_of_place": [], "in_place": []},
        "summary": {},
    }

    try:
        with open(log_file_path, "r", encoding="utf-8") as file:
            content = file.read()

        # Parse test configuration from first line
        config_match = re.search(
            r"# nThread (\d+) nGpus (\d+) minBytes (\d+) maxBytes (\d+) step: (\d+)\(factor\) warmup iters: (\d+) iters: (\d+)",
            content,
        )
        if config_match:
            result["test_info"] = {
                "nThread": int(config_match.group(1)),
                "nGpus": int(config_match.group(2)),
                "minBytes": int(config_match.group(3)),
                "maxBytes": int(config_match.group(4)),
                "step": int(config_match.group(5)),
                "warmup_iters": int(config_match.group(6)),
                "iters": int(config_match.group(7)),
            }

        # Parse device information
        device_pattern = r"#\s+Rank\s+(\d+)\s+Group\s+(\d+)\s+Pid\s+(\d+)\s+on\s+(\S+)\s+device\s+(\d+)\s+\[([^\]]+)\]\s+(.+)"
        devices = re.findall(device_pattern, content)

        for device in devices:
            result["devices"].append(
                {
                    "rank": int(device[0]),
                    "group": int(device[1]),
                    "pid": int(device[2]),
                    "hostname": device[3],
                    "device_id": int(device[4]),
                    "pci_id": device[5],
                    "gpu_name": device[6].strip(),
                }
            )

        # Parse performance data
        # Find the data section
        lines = content.split("\n")
        data_started = False

        for line in lines:
            # Skip until we reach the data section
            if (
                "#       size         count      type   redop    root     time   algbw   busbw #wrong     time   algbw   busbw #wrong"
                in line
            ):
                data_started = True
                continue

            if not data_started:
                continue

            # Stop parsing when we hit summary or end
            if line.strip().startswith("# Out of bounds") or line.strip().startswith(
                "# Avg bus bandwidth"
            ):
                break

            # Parse data lines (skip headers and comments)
            if line.strip() and not line.strip().startswith("#"):
                # Match data pattern: size, count, type, redop, root, out-of-place metrics, in-place metrics
                data_match = re.match(
                    r"\s*(\d+)\s+(\d+)\s+(\w+)\s+(\w+)\s+(-?\d+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+(\S+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+(\S+)",
                    line,
                )

                if data_match:
                    size_bytes = int(data_match.group(1))
                    count = int(data_match.group(2))
                    data_type = data_match.group(3)
                    redop = data_match.group(4)
                    root = int(data_match.group(5))

                    # Out-of-place metrics
                    oop_time = float(data_match.group(6))
                    oop_algbw = float(data_match.group(7))
                    oop_busbw = float(data_match.group(8))
                    oop_wrong = data_match.group(9)

                    # In-place metrics
                    ip_time = float(data_match.group(10))
                    ip_algbw = float(data_match.group(11))
                    ip_busbw = float(data_match.group(12))
                    ip_wrong = data_match.group(13)

                    base_data = {
                        "size_bytes": size_bytes,
                        "count": count,
                        "type": data_type,
                        "redop": redop,
                        "root": root,
                    }

                    result["performance_data"]["out_of_place"].append(
                        {
                            **base_data,
                            "time_us": oop_time,
                            "algbw_gbps": oop_algbw,
                            "busbw_gbps": oop_busbw,
                            "wrong": oop_wrong,
                        }
                    )

                    result["performance_data"]["in_place"].append(
                        {
                            **base_data,
                            "time_us": ip_time,
                            "algbw_gbps": ip_algbw,
                            "busbw_gbps": ip_busbw,
                            "wrong": ip_wrong,
                        }
                    )

        # Parse summary information
        avg_bandwidth_match = re.search(r"# Avg bus bandwidth\s+:\s+([0-9.]+)", content)
        if avg_bandwidth_match:
            result["summary"]["avg_bus_bandwidth_gbps"] = float(
                avg_bandwidth_match.group(1)
            )

        out_of_bounds_match = re.search(
            r"# Out of bounds values : (\d+) (\w+)", content
        )
        if out_of_bounds_match:
            result["summary"]["out_of_bounds_count"] = int(out_of_bounds_match.group(1))
            result["summary"]["out_of_bounds_status"] = out_of_bounds_match.group(2)

        logger.info(f"Successfully parsed NCCL test results from {log_file_path}")
        return result

    except Exception as e:
        logger.error(f"Error parsing NCCL test results: {str(e)}")
        raise


def collect(result_dir: str, run_id: str, run_url: str, cloud_info: str) -> None:
    """
    Collect and parse NCCL test results, saving them to a JSON file.

    Args:
        result_dir: Directory where the raw log file and results will be stored.
        run_id: RUN_ID associated with the NCCL test run.
        run_url: URL associated with the NCCL test run.
        cloud_info: Information about the cloud environment where the test was run.
    """
    try:
        logger.info("Collecting NCCL test results...")
        log_file = f"{result_dir}/raw.log"
        output_file = f"{result_dir}/results.json"
        nccl_result = _parse_nccl_test_results(log_file)

        result = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "operation_info": {
                "test_type": "rdma",
                "result": nccl_result,
                "cloud_info": cloud_info
            },
            "result": nccl_result,
            "run_id": run_id,
            "run_url": run_url,
        }
        with open(output_file, "a", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        logger.info(f"NCCL test results saved to {output_file}")

    except Exception as e:
        logger.error(f"Error collecting NCCL results: {str(e)}")
        raise


def main():
    """
    Main function to execute the script
    """
    parser = argparse.ArgumentParser(
        description="GPU and Network Operator Installation Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Configure command to install all operators
    configure_parser = subparsers.add_parser(
        "configure", help="Install all required operators (Network, GPU, and MPI)"
    )
    configure_parser.add_argument(
        "--efa_operator_version",
        type=str,
        required=False,
        default="",
        help="Version of the EFA device plugin to install",
    )
    configure_parser.add_argument(
        "--network_operator_version",
        type=str,
        required=False,
        default="",
        help="Version of the network operator to install",
    )
    configure_parser.add_argument(
        "--gpu_operator_version",
        type=str,
        required=False,
        default="",
        help="Version of the GPU operator to install",
    )
    configure_parser.add_argument(
        "--gpu_install_driver",
        type=str2bool,
        choices=[True, False],
        default=True,
        required=False,
        help="Install NVIDIA driver as part of GPU operator installation",
    )
    configure_parser.add_argument(
        "--gpu_enable_nfd",
        type=str2bool,
        choices=[True, False],
        default=False,
        required=False,
        help="Enable NVIDIA GPU feature discovery (NFD)",
    )
    configure_parser.add_argument(
        "--mpi_operator_version",
        type=str,
        required=False,
        default="",
        help="Version of the MPI operator to install",
    )
    configure_parser.add_argument(
        "--config_dir",
        type=str,
        required=True,
        help="Directory containing custom configuration files",
    )

    # Execute command to run NCCL tests
    execute_parser = subparsers.add_parser(
        "execute", help="Execute NCCL tests on the specified machine type and provider"
    )
    execute_parser.add_argument(
        "--provider",
        type=str,
        required=True,
        help="Cloud provider (e.g., 'azure', 'aws')",
    )
    execute_parser.add_argument(
        "--config_dir",
        type=str,
        required=True,
        help="Directory containing custom configuration files",
    )
    execute_parser.add_argument(
        "--result_dir",
        type=str,
        required=True,
        help="Directory containing result files",
    )
    execute_parser.add_argument(
        "--vm_size",
        type=str,
        required=False,
        default="",
        help="Type of the machine (e.g., 'ndv4', 'ndv5')",
    )

    # Collect command to parse NCCL test results
    collect_parser = subparsers.add_parser(
        "collect", help="Parse and collect NCCL test results from log files"
    )
    collect_parser.add_argument(
        "--result_dir",
        type=str,
        required=True,
        help="Path to the NCCL test result directory",
    )
    collect_parser.add_argument("--run_id", type=str, help="Run ID")
    collect_parser.add_argument("--run_url", type=str, help="Run URL")
    collect_parser.add_argument("--cloud_info", type=str, help="Cloud information")

    # Parse arguments
    args = parser.parse_args()

    # Execute based on command
    if args.command == "configure":
        configure(
            efa_operator_version=args.efa_operator_version,
            network_operator_version=args.network_operator_version,
            gpu_operator_version=args.gpu_operator_version,
            gpu_install_driver=args.gpu_install_driver,
            gpu_enable_nfd=args.gpu_enable_nfd,
            mpi_operator_version=args.mpi_operator_version,
            config_dir=args.config_dir,
        )
    elif args.command == "execute":
        execute(
            provider=args.provider,
            config_dir=args.config_dir,
            result_dir=args.result_dir,
            vm_size=args.vm_size,
        )
    elif args.command == "collect":
        collect(
            result_dir=args.result_dir,
            run_id=args.run_id,
            run_url=args.run_url,
            cloud_info=args.cloud_info,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
