import argparse
import json
import subprocess
from datetime import datetime, timezone

import yaml

from utils.common import str2bool
from utils.logger_config import get_logger, setup_logging
from utils.retries import execute_with_retries
from clients.kubernetes_client import KubernetesClient
from gpu.pkg.net import install_network_operator
from gpu.pkg.gpu import install_gpu_operator
from gpu.pkg.efa import install_efa_operator
from gpu.pkg.mpi import install_mpi_operator
from gpu.pkg.utils import parse_nccl_test_results, create_topology_configmap

# Configure logging
setup_logging()
logger = get_logger(__name__)
KUBERNETES_CLIENT = KubernetesClient()


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
        install_mpi_operator(chart_version=mpi_operator_version, config_dir=config_dir)


def execute(
    provider: str,
    config_dir: str,
    result_dir: str,
    topology_vm_size: str = "",
    gpu_node_count: int = 1,
    gpu_allocatable: int = 1,
    ib_allocatable: int = 1,
    efa_allocatable: int = 1,
    nccl_tests_version: str = "amd64",
):
    """
    Execute nccl-tests

    Args:
        provider: Cloud provider (e.g., "azure", "aws")
        config_dir: Directory containing custom configuration files
        result_dir: Directory to store results
        topology_vm_size: VM SKU family for topology (e.g., "ndv4", "ndv5").
                          When provided, creates and mounts topology configmap (Azure only)
        gpu_node_count: Number of GPU nodes (default: 1)
        gpu_allocatable: Number of GPUs per node (default: 1)
        ib_allocatable: Number of InfiniBand resources per node (Azure only, default: 1)
        efa_allocatable: Number of EFA resources per node (AWS only, default: 1)
        nccl_tests_version: NCCL tests image tag version (e.g., "amd64", "arm64", default: "amd64")
    """
    if gpu_node_count < 1:
        raise ValueError(f"gpu_node_count must be at least 1, got {gpu_node_count}")
    if gpu_allocatable < 1:
        raise ValueError(f"gpu_allocatable must be at least 1, got {gpu_allocatable}")

    try:
        subprocess.run(
            ["kubectl", "delete", "mpijob", "nccl-tests", "-n", "default", "--ignore-not-found=true"],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to delete existing MPIJob: {e.stderr}")

    replacements = {
        "slots_per_worker": gpu_allocatable,
        "number_of_processes": gpu_node_count * gpu_allocatable,
        "worker_replicas": gpu_node_count,
        "gpu_allocatable": gpu_allocatable,
        "nccl_tests_version": nccl_tests_version,
    }

    if provider.lower() == "azure":
        if ib_allocatable > 0:
            replacements["ib_allocatable"] = ib_allocatable
            if topology_vm_size:
                logger.info(f"Creating topology configmap for VM SKU: {topology_vm_size}")
                create_topology_configmap(vm_size=topology_vm_size)
                job_type = "topology"
            else:
                logger.info(f"Using SR-IOV with {ib_allocatable} InfiniBand resources per node")
                job_type = "sriov"
        else:
            logger.info("No SR-IOV device plugin found, using hostPath for InfiniBand")
            job_type = "hostpath"

        nccl_file = f"{config_dir}/mpi-operator/azure-job-{job_type}.yaml"
        logger.info(f"Running nccl-tests with {replacements} using {nccl_file}")
        nccl_template = KUBERNETES_CLIENT.create_template(nccl_file, replacements)
        nccl_dict = yaml.safe_load(nccl_template)
        KUBERNETES_CLIENT.apply_manifest_from_file(manifest_dict=nccl_dict)
    elif provider.lower() == "aws":
        replacements["efa_allocatable"] = efa_allocatable
        nccl_file = f"{config_dir}/mpi-operator/{provider}-job.yaml"

        logger.info(f"Running nccl-tests with {replacements} using {nccl_file}")
        nccl_template = KUBERNETES_CLIENT.create_template(nccl_file, replacements)
        nccl_dict = yaml.safe_load(nccl_template)
        KUBERNETES_CLIENT.apply_manifest_from_file(manifest_dict=nccl_dict)
    else:
        nccl_file = f"{config_dir}/mpi-operator/{provider}-job.yaml"

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


def collect(result_dir: str, run_id: str, run_url: str, cloud_info: str, nccl_tests_version: str = "amd64") -> None:
    """
    Collect and parse NCCL test results, saving them to a JSON file.

    Args:
        result_dir: Directory where the raw log file and results will be stored.
        run_id: RUN_ID associated with the NCCL test run.
        run_url: URL associated with the NCCL test run.
        cloud_info: Information about the cloud environment where the test was run.
        nccl_tests_version: NCCL tests image tag version (e.g., "amd64", "arm64", default: "amd64")
    """
    try:
        logger.info("Collecting NCCL test results...")
        log_file = f"{result_dir}/raw.log"
        output_file = f"{result_dir}/results.json"
        nccl_result = parse_nccl_test_results(log_file)

        result = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "operation_info": {
                "test_type": "rdma",
                "result": nccl_result,
                "cloud_info": cloud_info,
                "nccl_tests_version": nccl_tests_version
            },
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
        "--topology_vm_size",
        type=str,
        required=False,
        default="",
        choices=["", "ndv4", "ndv5"],
        help="VM SKU family for topology configmap (e.g., 'ndv4', 'ndv5'). When provided, creates and mounts topology configmap (Azure only)",
    )
    execute_parser.add_argument(
        "--gpu_node_count",
        type=int,
        required=False,
        default=1,
        help="Number of GPU nodes (default: 1)",
    )
    execute_parser.add_argument(
        "--gpu_allocatable",
        type=int,
        required=False,
        default=1,
        help="Number of GPUs per node (default: 1)",
    )
    execute_parser.add_argument(
        "--ib_allocatable",
        type=int,
        required=False,
        default=1,
        help="Number of InfiniBand resources per node (Azure only, default: 1)",
    )
    execute_parser.add_argument(
        "--efa_allocatable",
        type=int,
        required=False,
        default=1,
        help="Number of EFA resources per node (AWS only, default: 1)",
    )
    execute_parser.add_argument(
        "--nccl_tests_version",
        type=str,
        required=False,
        default="amd64",
        help="NCCL tests image tag version (e.g., 'amd64', 'arm64', default: 'amd64')",
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
    collect_parser.add_argument(
        "--nccl_tests_version",
        type=str,
        required=False,
        default="amd64",
        help="NCCL tests image tag version (e.g., 'amd64', 'arm64', default: 'amd64')",
    )

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
            topology_vm_size=args.topology_vm_size,
            gpu_node_count=args.gpu_node_count,
            gpu_allocatable=args.gpu_allocatable,
            ib_allocatable=args.ib_allocatable,
            efa_allocatable=args.efa_allocatable,
            nccl_tests_version=args.nccl_tests_version,
        )
    elif args.command == "collect":
        collect(
            result_dir=args.result_dir,
            run_id=args.run_id,
            run_url=args.run_url,
            cloud_info=args.cloud_info,
            nccl_tests_version=args.nccl_tests_version,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
