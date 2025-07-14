"""
AWS EKS Node Group CRUD Operations Module.

This module provides a cloud-agnostic NodePoolCRUD class for Amazon Elastic Kubernetes Service (EKS)
node groups, including create, scale (up/down), and delete operations. It supports
both direct and progressive scaling operations and handles GPU-enabled node groups.
"""

import logging
import time

from clients.eks_client import EKSClient
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)
# Suppress noisy AWS SDK logs
get_logger("boto3").setLevel(logging.WARNING)
get_logger("botocore").setLevel(logging.WARNING)


class NodePoolCRUD:
    """Performs EKS node group operations - metrics collection is handled directly by EKSClient"""

    def __init__(
        self,
        run_id=None,
        kube_config_file=None,
        result_dir=None,
        step_timeout=600,
        capacity_type="ON_DEMAND",
    ):
        """Initialize with AWS resource identifiers"""
        self.cluster_name = ""
        self.run_id = run_id
        self.capacity_type = capacity_type
        self.eks_client = EKSClient(
            kube_config_file=kube_config_file,
            result_dir=result_dir,
            operation_timeout_minutes=step_timeout / 60,  # Convert seconds to minutes
        )

        # Validate that EKS client was created successfully
        if self.eks_client is None:
            raise ValueError("Failed to initialize EKS client")

        self.step_timeout = step_timeout

    def create_node_pool(
        self,
        node_pool_name,
        instance_type=None,
        node_count=0,
        gpu_node_pool=False,
    ):
        """
        Create a new node group

        Args:
            node_pool_name: Name of the node group
            instance_type: VM size/instance type
            node_count: Number of nodes to create (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node group (default: False)

        Returns:
            The created node group object or False if creation failed
        """
        logger.info(
            f"Creating node group '{node_pool_name}' with {node_count} nodes (GPU: {gpu_node_pool})"
        )

        try:
            result = self.eks_client.create_node_group(
                node_group_name=node_pool_name,
                instance_type=instance_type,
                node_count=node_count,
                gpu_node_group=gpu_node_pool,
                capacity_type=self.capacity_type,
            )
            logger.info(f"Node group '{node_pool_name}' created successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to create node group '{node_pool_name}': {str(e)}")
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
        Scale a node group to specified count

        Args:
            node_pool_name: Name of the node group
            node_count: Desired node count
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node group (default: False)

        Returns:
            The scaled node group object or False if scaling failed
        """
        try:
            logger.info(
                f"Scaling node group '{node_pool_name}' to {node_count} nodes (Progressive: {progressive})"
            )

            result = self.eks_client.scale_node_group(
                node_group_name=node_pool_name,
                node_count=node_count,
                gpu_node_group=gpu_node_pool,
                progressive=progressive,
                scale_step_size=scale_step_size,
            )

            if result is not None:
                logger.info(
                    f"Node group '{node_pool_name}' scaled to {node_count} nodes successfully"
                )

            return result
        except Exception as e:
            logger.error(f"Failed to scale node group '{node_pool_name}': {str(e)}")
            return False

    def delete_node_pool(self, node_pool_name):
        """
        Delete a node group

        Args:
            node_pool_name: Name of the node group

        Returns:
            True if deletion was successful, False otherwise
        """
        logger.info(f"Deleting node group '{node_pool_name}'")

        try:
            result = self.eks_client.delete_node_group(node_group_name=node_pool_name)

            logger.info(f"Node group '{node_pool_name}' deleted successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to delete node group '{node_pool_name}': {str(e)}")
            return False

    def all(
        self,
        node_pool_name,
        vm_size=None,  # Cloud-agnostic parameter name (same as Azure)
        node_count=None,
        target_count=None,
        progressive=False,
        scale_step_size=1,
        gpu_node_pool=False,
        step_wait_time=30,
    ):
        """
        Unified method to perform all node group operations: create, scale-up, scale-down, delete
        It will perform all operations in sequence with a 30-second gap between each.

        Args:
            node_pool_name: Name of the node group
            vm_size: VM size/instance type
            node_count: Number of nodes to create (for create operation, default: 0)
            target_count: Target node count for scaling operations
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node group (default: False)
            step_wait_time: Time to wait between operations (default: 30 seconds)

        Returns:
            True if all operations succeeded, False if any operation failed
        """
        errors = []
        results = {
            "create": False,
            "scale_up": False,
            "scale_down": False,
            "delete": False,
        }

        try:
            # 1. Create node group
            logger.info(f"Starting to create node group '{node_pool_name}'")
            create_result = self.create_node_pool(
                node_pool_name=node_pool_name,
                instance_type=vm_size,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
            )
            results["create"] = create_result

            if create_result is False:
                error_msg = f"Create node group operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                return False

            logger.info(f"Waiting {step_wait_time} seconds before scaling up...")
            time.sleep(step_wait_time)

            # 2. Scale up
            logger.info(
                f"Scaling up node group '{node_pool_name}' to {target_count} nodes"
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

            logger.info(f"Waiting {step_wait_time} seconds before scaling down...")
            time.sleep(step_wait_time)

            # 3. Scale down (back to original count)
            logger.info(
                f"Scaling down node group '{node_pool_name}' back to {node_count} nodes"
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

            logger.info(f"Waiting {step_wait_time} seconds before deleting...")
            time.sleep(step_wait_time)

            # 4. Delete node group
            logger.info(f"Deleting node group '{node_pool_name}'")
            delete_result = self.delete_node_pool(node_pool_name=node_pool_name)
            results["delete"] = delete_result

            if delete_result is False:
                error_msg = f"Delete operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)

            # Check overall success
            if all(results.values()):
                logger.info(
                    "All operations completed successfully for node group '%s'",
                    node_pool_name,
                )
                return True

            failed_ops = [op for op, result in results.items() if result is False]
            logger.error("The following operations failed: %s", ", ".join(failed_ops))
            return False

        except Exception as e:
            error_msg = f"Failed to perform operations on node group '{node_pool_name}': {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            return False
