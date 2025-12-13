"""
Shared operator installation utilities.

This module provides common functions for installing various operators using Helm
and parsing NCCL test results.
"""

import subprocess
import os
import re
import requests
from typing import Dict, Any
from utils.logger_config import get_logger, setup_logging
from utils.constants import UrlConstants
from clients.kubernetes_client import KubernetesClient, client

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


def install_operator(
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
        "upgrade",
        operator_name,
        f"{repo_name}/{operator_name}",
        "--create-namespace",
        "--namespace",
        namespace,
        "--version",
        chart_version,
        "--install",
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


def parse_nccl_test_results(log_file_path: str) -> Dict[str, Any]:
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


def get_gpu_node_count_and_allocatable() -> tuple[int, int]:
    """
    Get the number of GPU nodes and the allocatable GPU resource per node,
    assuming each node has the same amount of GPU allocatable.

    Returns:
        tuple[int, int]: A tuple containing the number of GPU nodes and the allocatable GPU resources per node.
    """
    nodes = KUBERNETES_CLIENT.get_nodes(label_selector="gpu=true")
    if len(nodes) == 0:
        raise RuntimeError("No GPU nodes found in the cluster")
    gpu_node_count = len(nodes)

    gpu_allocatable = int(nodes[0].status.allocatable.get("nvidia.com/gpu", 0))
    if gpu_allocatable <= 0:
        raise RuntimeError("No allocatable GPU resources found on the GPU nodes")

    return gpu_node_count, gpu_allocatable


def create_topology_configmap(
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
