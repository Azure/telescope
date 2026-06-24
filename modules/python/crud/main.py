"""
Collect and process benchmark results, and handle node pool operations.

This module collects JSON result files from a specified directory and processes them
into a consolidated results file. It handles cluster data and operation information
from Kubernetes benchmark runs and formats them for further analysis.

It also provides command-line interface functions for handling node pool operations
such as create, scale, and delete operations.
"""

import argparse
import glob
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from crud.azure.node_pool_crud import NodePoolCRUD as AzureNodePoolCRUD
from crud.azure.machine_crud import MachineCRUD as AzureMachineCRUD
from crud.aws.node_pool_crud import NodePoolCRUD as AWSNodePoolCRUD
from crud.operation import OperationContext
from utils.common import get_env_vars
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)


def get_node_pool_crud_class(cloud_provider):
    """
    Dynamically import and return the appropriate NodePoolCRUD class based on cloud provider.

    Args:
        cloud_provider (str): The cloud provider ("azure", "aws", "gcp")

    Returns:
        class: The NodePoolCRUD class for the specified cloud provider

    Raises:
        ImportError: If the cloud provider implementation is not available
        ValueError: If the cloud provider is not supported
    """
    if cloud_provider == "azure":
        return AzureNodePoolCRUD
    if cloud_provider == "aws":
        return AWSNodePoolCRUD
    if cloud_provider == "gcp":
        # TODO: Implement GCP NodePoolCRUD class
        raise ValueError("GCP NodePoolCRUD implementation not yet available")

    raise ValueError(
        f"Unsupported cloud provider: {cloud_provider}. "
        f"Supported providers are: azure, aws, gcp"
    )


def get_machine_crud_class(cloud_provider):
    """
    Dynamically import and return the appropriate MachineCRUD class based on cloud provider.

    Only Azure is supported today; AWS and GCP do not expose an equivalent
    machine-level API.
    """
    if cloud_provider == "azure":
        return AzureMachineCRUD
    raise ValueError(
        f"Machine API is only supported on Azure today (got: {cloud_provider})"
    )


def collect_benchmark_results():
    """Main function to process Cluster Crud benchmark results."""
    result_dir = get_env_vars("RESULT_DIR")
    run_url = get_env_vars("RUN_URL")
    run_id = get_env_vars("RUN_ID")
    region = get_env_vars("REGION")
    logger.info("environment variable REGION: `%s`", region)
    logger.info("environment variable RESULT_DIR: `%s`", result_dir)
    logger.info("environment variable RUN_URL: `%s`", run_url)

    for filepath in glob.glob(f"{result_dir}/*.json"):
        if os.path.basename(filepath) == "results.json":
            continue
        logger.info("Processing file: `%s`", filepath)
        with open(filepath, "r", encoding="utf-8") as file:
            content = json.load(file)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "timestamp": timestamp,
            "region": region,
            "operation_info": json.dumps(content.get("operation_info")),
            "run_id": run_id,
            "run_url": run_url,
        }
        logger.debug("Result: %s", json.dumps(result))
        result_json = json.dumps(result)
        with open(f"{result_dir}/results.json", "a", encoding="utf-8") as file:
            file.write(result_json + "\n")
        logger.info("Result written to: `%s/results.json`", result_dir)
    return 0


def handle_node_pool_operation(node_pool_crud, args):
    """Handle node pool operations (create, scale, delete) based on the command"""
    command = args.command
    result = None

    # gpu_instance_profile / gpu_mig_strategy are Azure-only MIG inputs. The AWS
    # CRUD does not accept these kwargs (and has no **kwargs), so passing them for
    # --cloud aws would raise TypeError. Only forward them on Azure.
    azure_gpu_kwargs = {}
    if args.cloud == "azure":
        azure_gpu_kwargs = {
            "gpu_instance_profile": args.gpu_instance_profile,
            "gpu_mig_strategy": args.gpu_mig_strategy,
        }

    try:
        if command == "create":
            # Prepare create arguments
            create_kwargs = {
                "node_pool_name": args.node_pool_name,
                "vm_size": args.vm_size,
                "node_count": args.node_count,
                "gpu_node_pool": args.gpu_node_pool,
                "enable_managed_gpu": args.enable_managed_gpu,
                **azure_gpu_kwargs,
            }

            result = node_pool_crud.create_node_pool(**create_kwargs)

        elif command == "scale":
            # Prepare scale arguments
            scale_kwargs = {
                "node_pool_name": args.node_pool_name,
                "node_count": args.target_count,
                "progressive": check_for_progressive_scaling(args),
                "scale_step_size": args.scale_step_size,
                "gpu_node_pool": args.gpu_node_pool,
                "enable_managed_gpu": args.enable_managed_gpu,
                **azure_gpu_kwargs,
            }

            result = node_pool_crud.scale_node_pool(**scale_kwargs)

        elif command == "delete":
            result = node_pool_crud.delete_node_pool(node_pool_name=args.node_pool_name)

        elif command == "all":
            # Prepare all operation arguments
            all_kwargs = {
                "node_pool_name": args.node_pool_name,
                "vm_size": args.vm_size,
                "node_count": args.node_count,
                "target_count": args.target_count,
                "progressive": check_for_progressive_scaling(args),
                "scale_step_size": args.scale_step_size,
                "gpu_node_pool": args.gpu_node_pool,
                "enable_managed_gpu": args.enable_managed_gpu,
                "step_wait_time": args.step_wait_time,
                **azure_gpu_kwargs,
            }

            result = node_pool_crud.all(**all_kwargs)
        else:
            logger.error(f"Unsupported command: {command}")
            return 1

        # Check if the operation was successful
        if result is False:
            logger.error(f"Operation '{command}' failed")
            return 1
        return 0
    except Exception as e:
        logger.error(f"Error during '{command}' operation: {str(e)}")
        return 1

def handle_workload_operations(node_pool_crud, args):
    """Handle workload operations (deployment, statefulset, job) based on the command"""
    command = args.command
    result = None

    try:
        if command == "deployment":
            if not hasattr(node_pool_crud, 'create_deployment'):
                logger.error("Cloud provider does not support deployment workload operations")
                return 1

            # Prepare deploy arguments
            deploy_kwargs = {
                "node_pool_name": args.node_pool_name,
                "replicas": args.replicas,
                "manifest_dir": args.manifest_dir,
                "number_of_deployments": args.count,
                "label_selector": args.label_selector,
            }

            result = node_pool_crud.create_deployment(**deploy_kwargs)
        elif command == "statefulset":
            if not hasattr(node_pool_crud, 'create_statefulset'):
                logger.error("Cloud provider does not support statefulset workload operations")
                return 1

            # Prepare statefulset arguments
            statefulset_kwargs = {
                "node_pool_name": args.node_pool_name,
                "replicas": args.replicas,
                "manifest_dir": args.manifest_dir,
                "number_of_statefulsets": args.count,
                "label_selector": args.label_selector,
            }

            result = node_pool_crud.create_statefulset(**statefulset_kwargs)
        elif command == "job":
            if not hasattr(node_pool_crud, 'create_job'):
                logger.error("Cloud provider does not support job workload operations")
                return 1

            # Prepare job arguments
            job_kwargs = {
                "node_pool_name": args.node_pool_name,
                "completions": args.completions,
                "manifest_dir": args.manifest_dir,
                "number_of_jobs": args.count,
                "label_selector": args.label_selector,
            }

            result = node_pool_crud.create_job(**job_kwargs)
        else:
            logger.error("Unknown workload command: '%s'", command)
            return 1
        # Check if the operation was successful
        if result is False:
            logger.error(f"Operation '{command}' failed")
            return 1
        return 0
    except Exception as e:
        logger.error(f"Error during '{command}' operation: {str(e)}")
        return 1

def handle_node_pool_all(node_pool_crud, args):
    """Handle the all-in-one node pool operation command (create, scale up, scale down, delete)"""

    try:
        success = node_pool_crud.all(
            node_pool_name=args.node_pool_name,
            vm_size=args.vm_size,
            node_count=args.node_count,
            target_count=args.target_count,
            progressive=check_for_progressive_scaling(args),
            scale_step_size=args.scale_step_size
            if hasattr(args, "scale_step_size")
            else 1,
            gpu_node_pool=args.gpu_node_pool
            if hasattr(args, "gpu_node_pool")
            else False,
        )

        # The all method now returns a boolean success status
        if success:
            logger.info("All node pool operations completed successfully")
            return 0
        logger.error("One or more node pool operations failed")
        return 1
    except Exception as e:
        logger.error(f"Error during all operations sequence: {str(e)}")
        return 1


def handle_machine_operation(machine_crud, args):
    """Handle machine API operations (create-machine, scale-machine) based on the command."""
    command = args.command
    result = None

    try:
        if command == "create-machine":
            create_kwargs = {
                "agent_pool_name": args.node_pool_name,
                "vm_size": args.vm_size,
            }

            result = machine_crud.create_machine_agentpool(**create_kwargs)

        elif command == "scale-machine":
            tags = None
            if getattr(args, "tags", None):
                try:
                    tags = json.loads(args.tags)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse --tags {args.tags!r} as JSON: {e}")

            scale_kwargs = {
                "agent_pool_name": args.node_pool_name,
                "vm_size": args.vm_size,
                "scale_machine_count": args.scale_machine_count,
                "use_batch_api": args.use_batch_api,
                "machine_workers": args.machine_workers,
                "readiness_wait_timeout": args.readiness_wait_timeout,
                "tags": tags,
            }

            result = machine_crud.scale_machine(**scale_kwargs)

        else:
            logger.error(f"Unsupported machine command: {command}")
            return 1

        if result is False:
            logger.error(f"Machine operation '{command}' failed")
            return 1
        return 0
    except Exception as e:
        logger.error(f"Error during '{command}' operation: {e}")
        return 1


def check_for_progressive_scaling(args):
    """
    Check if we need to perform progressive scaling based on the scale step size and target count.

    """
    if hasattr(args, "scale_step_size") and args.scale_step_size != args.target_count:
        return True
    return False


def _add_create_machine_subparser(subparsers, common_parser):
    """Register the `create-machine` subcommand on the given subparsers group."""
    create_machine_parser = subparsers.add_parser(
        "create-machine",
        parents=[common_parser],
        help="Create a machine-mode agent pool via the AKS Machine API",
    )
    create_machine_parser.add_argument(
        "--node-pool-name", required=True, help="Agent pool name"
    )
    create_machine_parser.add_argument(
        "--vm-size", required=True, help="VM size for the agent pool"
    )
    create_machine_parser.set_defaults(func=handle_machine_operation)


def _add_scale_machine_subparser(subparsers, common_parser):
    """Register the `scale-machine` subcommand on the given subparsers group."""
    scale_machine_parser = subparsers.add_parser(
        "scale-machine",
        parents=[common_parser],
        help="Add N machines to a machine-mode agent pool via the AKS Machine API",
    )
    scale_machine_parser.add_argument(
        "--node-pool-name", required=True, help="Agent pool name"
    )
    scale_machine_parser.add_argument(
        "--vm-size", required=True, help="VM size for the new machines"
    )
    scale_machine_parser.add_argument(
        "--scale-machine-count",
        type=int,
        required=True,
        help="Number of machines to add to the agent pool",
    )
    scale_machine_parser.add_argument(
        "--machine-workers",
        type=int,
        default=1,
        help="Concurrent worker count for individual machine PUTs",
    )
    scale_machine_parser.add_argument(
        "--use-batch-api",
        action="store_true",
        help="Use the BatchPutMachine API (chunked, single PUT per chunk)",
    )
    scale_machine_parser.add_argument(
        "--readiness-wait-timeout",
        type=int,
        default=1200,
        help="Seconds to wait for nodes to become Ready after PUT",
    )
    scale_machine_parser.add_argument(
        "--tags",
        default=None,
        help="JSON-encoded tag map (currently ignored by the Machine API)",
    )
    scale_machine_parser.set_defaults(func=handle_machine_operation)


def main():
    """
    Main entry point that determines whether to run benchmark collection or node pool operations.
    """
    parser = argparse.ArgumentParser(
        description="Perform node pool operations and collect benchmark results."
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Collect benchmark results command (standalone, doesn't use common_parser)
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect and process benchmark results from JSON files in the result directory",
    )
    collect_parser.set_defaults(func=collect_benchmark_results)

    # Common arguments for all commands
    common_parser = argparse.ArgumentParser(add_help=False)
    # only suport Azure, Aws, GCP here
    common_parser.add_argument(
        "--cloud",
        choices=["azure", "aws", "gcp"],
        required=True,
        help="Cloud provider should be Azure, Aws or GCP",
    )
    common_parser.add_argument("--run-id", required=True, help="Unique run identifier")
    common_parser.add_argument(
        "--result-dir", default=".", help="Directory to save results"
    )
    common_parser.add_argument("--kube-config", help="Path to kubeconfig file")
    common_parser.add_argument(
        "--step-timeout",
        type=int,
        default=600,
        help="Wait time for each operation in seconds",
    )
    common_parser.add_argument(
        "--gpu-node-pool",
        action="store_true",
        help="Whether this is a GPU-enabled node pool",
    )
    common_parser.add_argument(
        "--enable-managed-gpu",
        action="store_true",
        help="Enable fully managed GPU mode (gpuProfile.nvidia.managementMode=Managed). "
             "When omitted with --gpu-node-pool, driver bootstrap only is used.",
    )
    common_parser.add_argument(
        "--gpu-instance-profile",
        default=None,
        help="MIG instance profile for Azure GPU node pools (e.g., MIG1g, MIG2g)",
    )
    common_parser.add_argument(
        "--gpu-mig-strategy",
        default=None,
        help="MIG strategy for Azure GPU node pools (e.g., mixed, single)",
    )
    common_parser.add_argument(
        "--capacity-type",
        choices=["ON_DEMAND", "SPOT", "CAPACITY_BLOCK"],
        default="ON_DEMAND",
        help="Capacity type for AWS/Azure node pool",
    )

    # Create command
    create_parser = subparsers.add_parser(
        "create", parents=[common_parser], help="Create a node pool"
    )
    create_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    create_parser.add_argument(
        "--vm-size",
        required=True,
        help="VM size for node pool (e.g., Standard_DS2_v2 for Azure, t3.medium for AWS)",
    )
    create_parser.add_argument(
        "--node-count", type=int, default=1, help="Number of nodes to create"
    )
    create_parser.set_defaults(func=handle_node_pool_operation)

    # Scale command
    scale_parser = subparsers.add_parser(
        "scale", parents=[common_parser], help="Scale a node pool"
    )
    scale_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    scale_parser.add_argument(
        "--target-count", type=int, required=True, help="Target node count"
    )

    scale_parser.add_argument(
        "--scale-step-size",
        type=int,
        default=1,
        help="Number of nodes to add/remove in each step during progressive scaling",
    )
    scale_parser.add_argument(
        "--step-wait-time",
        type=int,
        default=30,
        help="Wait time in seconds between scaling steps",
    )
    scale_parser.set_defaults(func=handle_node_pool_operation)

    # Delete command
    delete_parser = subparsers.add_parser(
        "delete", parents=[common_parser], help="Delete a node pool"
    )
    delete_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    delete_parser.set_defaults(func=handle_node_pool_operation)

    # All CRUD Operations command
    all_parser = subparsers.add_parser(
        "all",
        parents=[common_parser],
        help="Run full lifecycle: create, scale-up, scale-down, delete a node pool",
    )
    all_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    all_parser.add_argument(
        "--vm-size",
        required=True,
        default="Standard_DS2_v2",
        help="VM size for node pool (e.g., Standard_DS2_v2 for Azure, t3.medium for AWS) - for create operation",
    )
    all_parser.add_argument(
        "--node-count",
        type=int,
        required=True,
        default=1,
        help="Initial number of nodes to create",
    )
    all_parser.add_argument(
        "--target-count",
        type=int,
        required=True,
        help="Target node count for scale-up operation",
    )

    all_parser.add_argument(
        "--scale-step-size",
        type=int,
        default=1,
        help="Number of nodes to add/remove in each step (for progressive scaling)",
    )
    all_parser.add_argument(
        "--step-wait-time",
        type=int,
        default=30,
        help="Wait time between scaling steps in seconds (for progressive scaling)",
    )
    all_parser.set_defaults(func=handle_node_pool_operation)

    # Common arguments shared across all workload subcommands (deployment, statefulset, jobs)
    workload_common_parser = argparse.ArgumentParser(add_help=False)
    workload_common_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    workload_common_parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of workloads to create"
    )
    workload_common_parser.add_argument(
        "--replicas",
        type=int,
        default=10,
        help="Number of replicas per workload"
    )
    workload_common_parser.add_argument(
        "--manifest-dir",
        default=None,
        help="Directory containing Kubernetes manifest files"
    )
    workload_common_parser.add_argument(
        "--label-selector",
        default="app=nginx-container",
        help="Label selector for created pods (default: app=nginx-container)"
    )

    # Deployment command
    deployment_parser = subparsers.add_parser(
        "deployment",
        parents=[common_parser, workload_common_parser],
        help="create deployments"
    )
    deployment_parser.set_defaults(func=handle_workload_operations)

    # StatefulSet command
    statefulset_parser = subparsers.add_parser(
        "statefulset",
        parents=[common_parser, workload_common_parser],
        help="create statefulsets"
    )
    statefulset_parser.set_defaults(func=handle_workload_operations)

    # Job command
    job_parser = subparsers.add_parser(
        "job",
        parents=[common_parser, workload_common_parser],
        help="create jobs"
    )
    job_parser.add_argument(
        "--completions",
        type=int,
        default=1,
        help="Number of completions per job (default: 1)"
    )
    job_parser.set_defaults(func=handle_workload_operations)

    # Create-machine command (AKS Machine API)
    _add_create_machine_subparser(subparsers, common_parser)

    # Scale-machine command (AKS Machine API)
    _add_scale_machine_subparser(subparsers, common_parser)

    # Arguments provided, run node pool operations and collect benchmark results
    try:
        args = parser.parse_args()

        if not hasattr(args, "func"):
            logger.error("No command specified")
            parser.print_help()
            sys.exit(1)

        # Handle collect command separately since it doesn't need node pool operations
        if args.command == "collect":
            exit_code = args.func()
            if exit_code == 0:
                logger.info("Collect operation completed successfully")
            else:
                logger.error(f"Collect operation failed with exit code: {exit_code}")
            sys.exit(exit_code)

        # Handle machine API commands on their own dispatch path
        if args.command in ["create-machine", "scale-machine"]:
            machine_crud_class = get_machine_crud_class(args.cloud)
            logger.info(f"Using MachineCRUD class for cloud provider: {args.cloud}")
            machine_crud = machine_crud_class(
                resource_group=args.run_id,
                kube_config_file=args.kube_config,
                result_dir=args.result_dir,
                step_timeout=args.step_timeout,
            )
            exit_code = args.func(machine_crud, args)
            if exit_code == 0:
                logger.info("Operation completed successfully")
            else:
                logger.error(f"Operation failed with exit code: {exit_code}")
            sys.exit(exit_code)

        # Validate required arguments are present for node pool operations
        if args.command in ["create", "scale", "delete", "all"] and not hasattr(
            args, "node_pool_name"
        ):
            logger.error("--node-pool-name is required")
            sys.exit(1)

        if args.command == "create" and not hasattr(args, "vm_size"):
            logger.error("--vm-size is required for create command")
            sys.exit(1)

        if args.command == "scale" and not hasattr(args, "target_count"):
            logger.error("--target-count is required for scale command")
            sys.exit(1)

        if args.command == "all":
            if not hasattr(args, "vm_size"):
                logger.error("--vm-size is required for all command")
                sys.exit(1)
            if not hasattr(args, "node_count"):
                logger.error("--node-count is required for all command")
                sys.exit(1)
            if not hasattr(args, "target_count"):
                logger.error("--target-count is required for all command")
                sys.exit(1)

        # Get the appropriate NodePoolCRUD class for the specified cloud provider
        NodePoolCRUD = get_node_pool_crud_class(args.cloud)  # pylint: disable=invalid-name
        logger.info(f"Using NodePoolCRUD class for cloud provider: {args.cloud}")

        # Create a single NodePoolCRUD instance to be used across all operations
        if args.cloud == "azure":
            node_pool_crud = NodePoolCRUD(
                resource_group=args.run_id,
                kube_config_file=args.kube_config,
                result_dir=args.result_dir,
                step_timeout=args.step_timeout,
            )
        elif args.cloud == "aws":
            node_pool_crud = NodePoolCRUD(
                run_id=args.run_id,
                kube_config_file=args.kube_config,
                result_dir=args.result_dir,
                step_timeout=args.step_timeout,
                capacity_type=args.capacity_type
                if hasattr(args, "capacity_type")
                else None,
            )
        else:
            logger.error(
                f"NodePoolCRUD instantiation not implemented for cloud provider: {args.cloud}"
            )
            sys.exit(1)

        # Install GPU device plugin for managed (driver bootstrap) and AWS GPU pools.
        # Fully managed GPU skips this — AKS installs nvidia-device-plugin as a systemd service.
        if args.gpu_node_pool and args.cloud in ["azure", "aws"] and not args.enable_managed_gpu:
            logger.info("GPU node pool is enabled")
            with OperationContext(
                "install_gpu_plugin", args.cloud, {}, result_dir=args.result_dir
            ) as op:
                # Get the appropriate client based on cloud provider
                if args.cloud == "azure":
                    k8s_client = node_pool_crud.aks_client.k8s_client
                elif args.cloud == "aws":
                    k8s_client = node_pool_crud.eks_client.k8s_client
                else:
                    logger.error(
                        f"GPU plugin installation not supported for cloud provider: {args.cloud}"
                    )
                    op.success = False
                    sys.exit(1)

                if k8s_client:
                    k8s_client.install_gpu_device_plugin()
                    valid = k8s_client.verify_gpu_device_plugin()
                    if not valid:
                        logger.error("GPU device plugin verification failed")
                        op.success = False
                    else:
                        logger.info(
                            "GPU device plugin installed and verified successfully"
                        )
                else:
                    logger.warning(
                        "Kubernetes client not available - skipping GPU plugin installation"
                    )
                    logger.info(
                        "Make sure to install GPU device plugin manually if needed"
                    )

        # Execute the function associated with the selected command
        operation_result = args.func(node_pool_crud, args)
        if operation_result is None:
            # For backward compatibility, treat None as success
            logger.info("Operation '%s' completed successfully", args.command)
            exit_code = 0
        elif isinstance(operation_result, bool):
            # Convert boolean to exit code
            exit_code = 0 if operation_result else 1
        else:
            # Return the explicit exit code
            exit_code = operation_result

        if exit_code == 0:
            logger.info("Operation completed successfully")
        else:
            logger.error(f"Operation failed with exit code: {exit_code}")

    except ImportError as import_error:
        error_msg = f"Import Error: {import_error}"
        logger.critical(error_msg)
        error_trace = traceback.format_exc()
        logger.critical(error_trace)
        sys.exit(1)
    except Exception as general_error:
        error_msg = f"Unexpected error: {general_error}"
        logger.critical(error_msg)
        error_trace = traceback.format_exc()
        logger.critical(error_trace)
        sys.exit(1)


if __name__ == "__main__":
    main()
