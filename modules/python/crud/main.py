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

    try:
        if command == "create":
            # Prepare create arguments
            create_kwargs = {
                "node_pool_name": args.node_pool_name,
                "vm_size": args.vm_size,
                "node_count": args.node_count,
                "gpu_node_pool": args.gpu_node_pool,
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
                "step_wait_time": args.step_wait_time,
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


def check_for_progressive_scaling(args):
    """
    Check if we need to perform progressive scaling based on the scale step size and target count.

    """
    if hasattr(args, "scale_step_size") and args.scale_step_size != args.target_count:
        return True
    return False


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

        # Install GPU device plugin if GPU node pool is enabled and verify the plugin is installed
        if args.gpu_node_pool and args.cloud in ["azure", "aws"]:
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
            sys.exit(exit_code)

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
