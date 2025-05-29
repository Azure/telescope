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
import time
from datetime import datetime, timezone

from azure.node_pool_crud import NodePoolCRUD as AzureNodePoolCRUD
from utils.common import get_env_vars, save_info_to_file
from utils.operation import OperationContext
from utils.logger_config import get_logger, setup_logging


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
        try:
            return AzureNodePoolCRUD
        except ImportError as e:
            raise ImportError(f"Azure NodePoolCRUD implementation not found: {e}") from e
    # Todo : Implement AWS and GCP NodePoolCRUD classes
    else:
        raise ValueError(f"Unsupported cloud provider: {cloud_provider}. "
                        f"Supported providers are: azure, aws, gcp")

# Configure logging
setup_logging()
logger = get_logger(__name__)


def create_result_dir(path):
    """
    Create result directory if it doesn't exist.

    Args:
        path: The directory path to create
    """
    if not os.path.exists(path):
        logger.info("Creating result directory: `%s`", path)
        os.makedirs(path)


def collect_benchmark_results():
    """Main function to process Cluster Crud benchmark results."""
    result_dir = get_env_vars("RESULT_DIR")
    run_url = get_env_vars("RUN_URL")
    run_id = get_env_vars("RUN_ID")
    region = get_env_vars("REGION")
    logger.info("environment variable REGION: `%s`", region)
    logger.info("environment variable RESULT_DIR: `%s`", result_dir)
    logger.info("environment variable RUN_URL: `%s`", run_url)

    create_result_dir(result_dir)

    for filepath in glob.glob(f"{result_dir}/*.json"):
        if os.path.basename(filepath) == "results.json":
            continue
        logger.info("Processing file: `%s`", filepath)
        with open(filepath, "r", encoding="utf-8") as file:
            content = json.load(file)
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        result = {
            "timestamp": timestamp,
            "region": region,
            "operation_info": json.dumps(content.get("operation_info")),
            "run_id": run_id,
            "run_url": run_url,
        }
        logger.debug("Result: %s", json.dumps(result))
        save_info_to_file(result, os.path.join(result_dir, "results.json"))
        logger.info("Result written to: `%s/results.json`", result_dir)


def handle_node_pool_operation(node_pool_crud, args):
    """Handle node pool operations (create, scale, delete) based on the command"""
    command = args.command
    result = None

    try:
        if command == "create":
            result = node_pool_crud.create_node_pool(
                node_pool_name=args.node_pool_name,
                vm_size=args.vm_size,
                node_count=args.node_count,
                gpu_node_pool=args.gpu_node_pool,
            )
        elif command == "scale":
            result = node_pool_crud.scale_node_pool(
                node_pool_name=args.node_pool_name,
                node_count=args.target_count,
                progressive=args.progressive,
                scale_step_size=args.scale_step_size,
                gpu_node_pool=args.gpu_node_pool,
            )
        elif command == "delete":
            result = node_pool_crud.delete_node_pool(node_pool_name=args.node_pool_name)
        elif command == "all":
            result = node_pool_crud.all(
                node_pool_name=args.node_pool_name,
                vm_size=args.vm_size,
                node_count=args.node_count,
                target_count=args.target_count,
                progressive=args.progressive,
                scale_step_size=args.scale_step_size,
                gpu_node_pool=args.gpu_node_pool,
            )
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
            progressive=args.progressive if hasattr(args, "progressive") else False,
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


def node_pool_operations_main():
    """Main entry point for node pool operations"""
    parser = argparse.ArgumentParser(description="Perform AKS node pool operations")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Common arguments for all commands
    common_parser = argparse.ArgumentParser(add_help=False)
    # only suport Azure, Aws, GCP here
    common_parser.add_argument("--cloud", choices=["azure", "aws", "gcp"], required=True, help="Cloud provider should be Azure, Aws or GCP")
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

    # Create command
    create_parser = subparsers.add_parser(
        "create", parents=[common_parser], help="Create a node pool"
    )
    create_parser.add_argument("--node-pool-name", required=True, help="Node pool name")
    create_parser.add_argument(
        "--vm-size", default="Standard_DS2_v2", help="VM size for node pool"
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
        "--progressive", action="store_true", help="Scale progressively in steps"
    )
    scale_parser.add_argument(
        "scale-step-size",
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
        help="VM size for node pool (for create operation)",
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
        "--progressive",
        action="store_true",
        help="Scale progressively in steps (for scaling operations)",
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

    args = parser.parse_args()

    if not hasattr(args, "func"):
        logger.error("No command specified")
        parser.print_help()
        return 1

    # Validate required arguments are present
    if args.command in ["create", "scale", "delete", "all"] and not args.node_pool_name:
        logger.error("--node-pool-name is required")
        return 1

    if args.command == "create" and not args.vm_size:
        logger.error("--vm-size is required for create command")
        return 1

    if args.command == "scale" and args.target_count is None:
        logger.error("--target-count is required for scale command")
        return 1

    if args.command == "all":
        if not args.vm_size:
            logger.error("--vm-size is required for all command")
            return 1
        if args.node_count is None:
            logger.error("--node-count is required for all command")
            return 1
        if args.target_count is None:
            logger.error("--target-count is required for all command")
            return 1

    try:
        # Get the appropriate NodePoolCRUD class for the specified cloud provider
        NodePoolCRUD = get_node_pool_crud_class(args.cloud)
        logger.info(f"Using NodePoolCRUD class for cloud provider: {args.cloud}")
        # Create a single NodePoolCRUD instance to be used across all operations
        node_pool_crud = NodePoolCRUD(
            resource_group=args.run_id,
            kube_config_file=args.kube_config,
            result_dir=args.result_dir,
            step_timeout=args.step_timeout,
        )
        # Install GPU device plugin if GPU node pool is enabled and verify the plugin is installed
        if args.gpu_node_pool:
            logger.info("GPU node pool is enabled")
            with OperationContext(
                "install_gpu_plugin", args.cloud, {}, result_dir=args.result_dir
            ) as op:
                node_pool_crud.aks_client.k8s_client.install_gpu_device_plugin()
                valid = node_pool_crud.aks_client.k8s_client.verify_gpu_device_plugin()
                if not valid:
                    logger.error("GPU device plugin verification failed")
                    exit (1)
                logger.info("GPU device plugin installed and verified successfully")


        # Execute the function associated with the selected command
        operation_result = args.func(node_pool_crud, args)
        if operation_result is None:
            # For backward compatibility, treat None as success
            logger.info("Operation '%s' completed successfully", args.command)
            return 0
        if isinstance(operation_result, bool):
            # Convert boolean to exit code
            return 0 if operation_result else 1
        # Return the explicit exit code
        return operation_result

    except (ImportError, ValueError) as e:
        logger.error(f"Cloud provider configuration error: {str(e)}")
        return 1
    except Exception as e:
        logger.error(f"Error executing command: {str(e)}")
        return 1


def main():
    """
    Main entry point that determines whether to run benchmark collection or node pool operations.
    
    If no command line arguments are provided, runs benchmark collection.
    Otherwise, runs node pool operations.
    """
    if len(sys.argv) == 1:
        # No arguments provided, run benchmark collection
        collect_benchmark_results()
    else:
        # Arguments provided, run node pool operations
        try:
            exit_code = node_pool_operations_main()
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
