"""
Azure AKS Node Pool CRUD Operations Module.

This module provides comprehensive CRUD operations for Azure Kubernetes Service (AKS)
node pools, including create, scale (up/down), and delete operations. It supports
both direct and progressive scaling operations and handles GPU-enabled node pools.
"""

import argparse
import os
import logging
import sys
import time
import traceback

from clients.aks_client import AKSClient
from utils.logger_config import get_logger, setup_logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
setup_logging()
logger = get_logger(__name__)
# Suppress noisy Azure SDK logs
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.ERROR
)
logging.getLogger("azure.identity").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline").setLevel(logging.ERROR)
logging.getLogger("msal").setLevel(logging.ERROR)


class NodePoolCRUD:
    """Performs AKS node pool operations - metrics collection is handled directly by AKSClient"""

    def __init__(self, resource_group, kube_config_file=None, result_dir=None, step_timeout=600):
        """Initialize with Azure resource identifiers"""
        self.resource_group = resource_group
        self.aks_client = AKSClient(
            resource_group=resource_group,
            kube_config_file=kube_config_file,
            result_dir=result_dir,
            operation_timeout_minutes=step_timeout/60,  # Convert seconds to minutes
        )

        if not self.aks_client:
            error_msg = "Failed to initialize AKS client."
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Get the cluster name when initializing
        self.cluster_name = self.aks_client.get_cluster_name()
        self.step_timeout = step_timeout

    def create_node_pool(
        self, node_pool_name, vm_size, node_count=1, gpu_node_pool=False
    ):
        """
        Create a new node pool

        Args:
            node_pool_name: Name of the node pool
            vm_size: VM size for the nodes
            node_count: Number of nodes to create (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            The created node pool object or False if creation failed
        """
        logger.info(
            f"Creating node pool '{node_pool_name}' with {node_count} nodes (GPU: {gpu_node_pool})"
        )

        try:
            result = self.aks_client.create_node_pool(
                node_pool_name=node_pool_name,
                vm_size=vm_size,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
            )
            logger.info(f"Node pool '{node_pool_name}' created successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to create node pool '{node_pool_name}': {str(e)}")
            return False

    def scale_node_pool(
        self,
        node_pool_name,
        node_count,
        progressive=False,
        scale_step_size=1,
        gpu_node_pool=False,
    ):
        """
        Scale a node pool to specified count

        Args:
            node_pool_name: Name of the node pool
            node_count: Desired node count
            operation_type: Type of scaling operation (scale, scale_up, scale_down)
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            The scaled node pool object or False if scaling failed
        """
        try:
            # Get current node pool info for logging
            current_pool = self.aks_client.get_node_pool(node_pool_name)
            current_count = current_pool.count
            logger.info(f"Current node count: {current_count}, target: {node_count}")

            if current_count < node_count:
                operation_type = "scale_up"
            elif current_count > node_count:
                operation_type = "scale_down"
            else:
                return current_pool

            # If progressive scaling is requested
            if progressive and current_count != node_count:
                return self._progressive_scale(
                    node_pool_name=node_pool_name,
                    current_count=current_count,
                    target_count=node_count,
                    scale_step_size=scale_step_size,
                    operation_type=operation_type,
                    gpu_node_pool=gpu_node_pool,
                )

            # Otherwise, perform direct scaling
            logger.info(
                f"{operation_type.replace('_', ' ').title()} node pool '{node_pool_name}' from {current_count} to {node_count} nodes"
            )
            result = self.aks_client.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=node_count,
                operation_type=operation_type,
                gpu_node_pool=gpu_node_pool,
            )

            logger.info(
                f"Node pool '{node_pool_name}' {operation_type.replace('_', ' ')}d to {node_count} nodes successfully"
            )

            return result
        except Exception as e:
            logger.error(
                f"Failed to {operation_type.replace('_', ' ')} node pool '{node_pool_name}': {str(e)}"
            )
            return False

    def _progressive_scale(
        self,
        node_pool_name,
        current_count,
        target_count,
        scale_step_size=1,
        operation_type="scale",
        gpu_node_pool=False,
    ):
        """
        Scale a node pool progressively with specified step size

        Args:
            node_pool_name: Name of the node pool
            current_count: Starting node count
            target_count: Final desired node count
            scale_step_size: Number of nodes to add/remove in each step (default: 1)
            operation_type: Type of scaling operation (scale_up or scale_down)

        Returns:
            The final node pool object or False if scaling failed
        """
        logger.info(
            f"Starting progressive scaling for node pool '{node_pool_name}' from {current_count} to {target_count} nodes (step size: {scale_step_size})"
        )

        # Determine if we're scaling up or down
        scaling_up = current_count < target_count
        operation_type = "scale_up" if scaling_up else "scale_down"

        # Calculate the steps
        if scaling_up:
            steps = range(current_count + scale_step_size, target_count + 1, scale_step_size)
        else:
            steps = range(current_count - scale_step_size, target_count - 1, -scale_step_size)

        # Ensure the final step is exactly the target count
        if steps and steps[-1] != target_count:
            steps = list(steps)
            if target_count not in steps:
                steps.append(target_count)

        # If there are no intermediate steps, just add the target directly
        if not steps:
            steps = [target_count]

        result = None

        # Execute scaling operation for each step
        for step in steps:
            logger.info(
                f"Scaling from {current_count if step == steps[0] else steps[steps.index(step) - 1]} to {step} nodes"
            )

            result = self.aks_client.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=step,
                operation_type=operation_type,
                gpu_node_pool=gpu_node_pool,
            )

            if result is None:
                logger.error(f"Progressive scaling failed at step {step}")
                return False

            # Wait between steps if not the last step
            if step != steps[-1] and self.step_timeout > 0:
                logger.info(f"Waiting {self.step_timeout}s before next scaling operation...")
                time.sleep(self.step_timeout)

        logger.info(
            f"Progressive scaling from {current_count} to {target_count} completed successfully"
        )
        return result

    def delete_node_pool(self, node_pool_name):
        """
        Delete a node pool

        Args:
            node_pool_name: Name of the node pool

        Returns:
            True if deletion was successful, False otherwise
        """
        logger.info(f"Deleting node pool '{node_pool_name}'")

        try:
            result = self.aks_client.delete_node_pool(node_pool_name=node_pool_name)

            logger.info(f"Node pool '{node_pool_name}' deleted successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to delete node pool '{node_pool_name}': {str(e)}")
            return False

    def all(
        self,
        node_pool_name,
        vm_size=None,
        node_count=None,
        target_count=None,
        progressive=False,
        scale_step_size=1,
        gpu_node_pool=False,
    ):
        """
        Unified method to perform all node pool operations: create, scale-up, scale-down, delete
        It will perform all operations in sequence with a 30-second gap between each.

        Args:
            node_pool_name: Name of the node pool
            vm_size: VM size for nodes (required for create operation)
            node_count: Number of nodes to create (for create operation, default: 0)
            target_count: Target node count for scaling operations
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            True if all operations succeeded, False if any operation failed
        """
        operations_gap = 30  # Default gap between operations
        errors = []
        results = {
            "create": False,
            "scale_up": False,
            "scale_down": False,
            "delete": False,
        }

        try:
            # 1. Create node pool
            logger.info(f"Starting to create node pool '{node_pool_name}'")
            create_result = self.create_node_pool(
                node_pool_name=node_pool_name,
                vm_size=vm_size,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
            )
            results["create"] = create_result

            if create_result is False:
                error_msg = f"Create node pool operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                return False

            logger.info(f"Waiting {operations_gap} seconds before scaling up...")
            time.sleep(operations_gap)

            # 2. Scale up
            logger.info(
                f"Scaling up node pool '{node_pool_name}' to {target_count} nodes"
            )
            scale_up_result = self.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=target_count,
                progressive=progressive,
                scale_step_size=scale_step_size,
                gpu_node_pool=gpu_node_pool,
            )
            results["scale_up"] = scale_up_result

            if scale_up_result is False:
                error_msg = f"Scale up operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                # Continue to scale down and delete to clean up resources

            logger.info(f"Waiting {operations_gap} seconds before scaling down...")
            time.sleep(operations_gap)

            # 3. Scale down (back to original count)
            logger.info(
                f"Scaling down node pool '{node_pool_name}' back to {node_count} nodes"
            )
            scale_down_result = self.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=node_count,
                progressive=progressive,
                scale_step_size=scale_step_size,
                gpu_node_pool=gpu_node_pool,
            )
            results["scale_down"] = scale_down_result

            if scale_down_result is False:
                error_msg = f"Scale down operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                # Continue to delete to clean up resources

            logger.info(f"Waiting {operations_gap} seconds before deleting...")
            time.sleep(operations_gap)

            # 4. Delete node pool
            logger.info(f"Deleting node pool '{node_pool_name}'")
            delete_result = self.delete_node_pool(node_pool_name=node_pool_name)
            results["delete"] = delete_result

            if delete_result is False:
                error_msg = f"Delete operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)

            # Check overall success
            if all(results.values()):
                logger.info(
                    "All operations completed successfully for node pool '%s'",
                    node_pool_name,
                )
                return True

            failed_ops = [op for op, result in results.items() if result is False]
            logger.error("The following operations failed: %s", ", ".join(failed_ops))
            return False

        except Exception as e:
            error_msg = f"Failed to perform operations on node pool '{node_pool_name}': {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            return False


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


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Perform AKS node pool operations")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Common arguments for all commands
    common_parser = argparse.ArgumentParser(add_help=False)
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
        # Create a single NodePoolCRUD instance to be used across all operations
        node_pool_crud = NodePoolCRUD(
            resource_group=args.run_id,
            kube_config_file=args.kube_config,
            result_dir=args.result_dir,
            step_timeout=args.step_timeout,

        )

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

    except Exception as e:
        logger.error(f"Error executing command: {str(e)}")
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
            scale_step_size=args.scale_step_size if hasattr(args, "scale_step_size") else 1,
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


if __name__ == "__main__":
    try:
        exit_code = main()
        if exit_code == 0:
            logger.info("Operation completed successfully")
        else:
            logger.error(f"Operation failed with exit code: {exit_code}")
        logger.error(f"Exiting with code: {exit_code}")
        sys.exit(exit_code)
    except ImportError as import_error:
        ERROR_MSG = f"Import Error: {import_error}"
        logger.critical(ERROR_MSG)

        ERROR_TRACE = traceback.format_exc()
        logger.critical(ERROR_TRACE)
        sys.exit(1)
    except Exception as general_error:
        ERROR_MSG = f"Unexpected error: {general_error}"
        logger.critical(ERROR_MSG)

        ERROR_TRACE = traceback.format_exc()
        logger.critical(ERROR_TRACE)
        sys.exit(1)
