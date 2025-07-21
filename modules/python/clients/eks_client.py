"""
EKS Client Module

This module provides a client for interacting with Amazon Elastic Kubernetes Service (EKS),
focusing specifically on node group operations (create, scale, delete).
It handles authentication with AWS services using boto3.
The client also validates node readiness after operations using Kubernetes API.
Operations are tracked using the Operation and OperationContext classes for metrics
and troubleshooting.
"""
# pylint: disable=too-many-lines

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import json

# Third party imports
import boto3
from botocore.exceptions import ClientError, WaiterError
import semver

# Local imports
from utils.logger_config import get_logger, setup_logging
from utils.common import get_env_vars
from .kubernetes_client import KubernetesClient

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Suppress noisy boto3 logs
get_logger("boto3").setLevel(logging.WARNING)
get_logger("botocore").setLevel(logging.WARNING)


class EKSClient:
    """
    Client for Amazon Elastic Kubernetes Service (EKS) operations.

    This client handles authentication with AWS services and provides
    methods for managing EKS node groups (create, scale, delete).
    It also validates node readiness using Kubernetes API.
    """

    def _get_operation_context(self):
        """Get operation context for tracking"""
        from crud.operation import OperationContext  # pylint: disable=import-outside-toplevel

        return OperationContext

    def _serialize_aws_response(self, obj):
        """
        Convert AWS API response objects to JSON-serializable format.

        Args:
            obj: AWS API response object or dictionary

        Returns:
            JSON-serializable dictionary
        """

        class DateTimeEncoder(json.JSONEncoder):
            def default(self, obj):  # pylint: disable=arguments-renamed
                if isinstance(obj, datetime):
                    # Format as "2025-07-07T14:44:21Z"
                    return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
                return super().default(obj)

        # Convert to JSON string and back to dict to ensure all datetime objects are converted
        json_str = json.dumps(obj, cls=DateTimeEncoder, default=str)
        return json.loads(json_str)

    def __init__(
        self,
        kube_config_file: Optional[str] = os.path.expanduser("~/.kube/config"),
        result_dir: Optional[str] = None,
        operation_timeout_minutes: int = 40,
    ):
        """
        Initialize the EKS client.

        Args:
            cluster_name: Name of the EKS cluster
            kube_config_file: Path to the Kubernetes config file (optional)
            result_dir: Directory to store operation results (optional)
            operation_timeout_minutes: Maximum time to wait for operations (default: 20 minutes)
        """

        self.region = get_env_vars("AWS_DEFAULT_REGION")
        self.kube_config_file = kube_config_file
        self.result_dir = result_dir
        self.operation_timeout_minutes = operation_timeout_minutes
        self.vm_size = None
        self.launch_template_id = None
        self.k8s_version = None

        try:
            self.eks = boto3.client("eks", region_name=self.region)
            # Initialize the EC2 client for the VPC configuration
            self.ec2 = boto3.client("ec2", region_name=self.region)
            # Initialize the IAM client for the role ARN
            self.iam = boto3.client("iam", region_name=self.region)
            self.run_id = get_env_vars("RUN_ID")
            self.cluster_name = self._get_cluster_name_by_run_id(self.run_id)
            logger.info(
                "Successfully connected to AWS EKS. Found cluster: %s",
                self.cluster_name,
            )
            self._load_subnet_ids()
            self._load_node_role_arn()

        except Exception as e:
            logger.error("Initialization failed: %s", e)
            raise

        # Initialize Kubernetes client if provided or if kubeconfig is available
        try:
            self.k8s_client = KubernetesClient(config_file=kube_config_file)
            logger.info("Kubernetes client initialized successfully")
        except Exception as e:
            logger.warning("Failed to initialize Kubernetes client: %s", str(e))
            self.k8s_client = None
        logger.info("EKS client initialized successfully")

    def _get_cluster_name_by_run_id(self, run_id: str) -> Optional[str]:
        """
        Find the EKS cluster tagged with a specific run_id.

        Args:
            run_id (str): The run_id tag value to search for.

        Returns:
            Optional[str]: The name of the matching cluster or None.
        """
        try:
            all_clusters = self.eks.list_clusters()["clusters"]
            logger.info(
                "Checking %d clusters for run_id = %s", len(all_clusters), run_id
            )

            for cluster_name in all_clusters:
                details = self.eks.describe_cluster(name=cluster_name)
                tags = details["cluster"].get("tags", {})

                if tags.get("run_id") == run_id:
                    logger.info(
                        "Matched cluster: %s with run_id: %s", cluster_name, run_id
                    )
                    # get k8s version and set it in the client
                    self.k8s_version = details["cluster"].get("version")
                    logger.info("Kubernetes version for cluster %s: %s", cluster_name, self.k8s_version)
                    return cluster_name
            raise Exception("No EKS cluster found with run_id: " + run_id)
        except Exception as e:
            logger.error("Error while getting EKS clusters : %s", e)
            raise

    def _load_subnet_ids(self):
        """
        Loads the subnet IDs based on the run ID.

        Raises:
            Exception: If no subnets are found with the given run ID.
        """
        response = self.ec2.describe_subnets(
            Filters=[
                {"Name": "tag:run_id", "Values": [self.run_id]},
            ]
        )
        logger.debug(response)
        self.subnets = [subnet["SubnetId"] for subnet in response["Subnets"]]
        self.subnet_azs = [subnet["AvailabilityZone"] for subnet in response["Subnets"]]
        logger.info("Subnets: %s", self.subnets)
        logger.info("Subnet Availability Zones: %s", self.subnet_azs)
        if self.subnets == []:
            raise Exception("No subnets found for run_id: " + self.run_id)

    def _load_node_role_arn(self):
        """
        Load the IAM role ARN for EKS node groups from the cluster.

        Raises:
            Exception: If no suitable role is found
        """
        try:
            # Try to find existing node groups to get the role
            response = self.eks.list_nodegroups(clusterName=self.cluster_name)
            if response["nodegroups"]:
                # Get the first node group's role as template
                first_ng = response["nodegroups"][0]
                ng_info = self.get_node_group(first_ng)
                self.node_role_arn = ng_info["nodeRole"]
                logger.info(
                    "Found node role ARN from existing node group: %s",
                    self.node_role_arn,
                )
                return
        except Exception as e:
            logger.warning("Could not find existing node group role: %s", e)

    def get_cluster_data(self, cluster_name: Optional[str] = None) -> Dict:
        """
        Retrieve cluster information from EKS.

        Args:
            cluster_name: The name of the EKS cluster (optional, uses initialized cluster if not provided)

        Returns:
            Dictionary containing cluster information

        Raises:
            ClientError: If the AWS API request fails
        """
        cluster_name = cluster_name or self.cluster_name

        try:
            response = self.eks.describe_cluster(name=cluster_name)
            cluster = response["cluster"]

            # Convert the cluster object to a serializable dictionary
            cluster_data = (
                cluster.as_dict() if hasattr(cluster, "as_dict") else dict(cluster)
            )

            # Serialize to handle datetime objects
            return self._serialize_aws_response(cluster_data)
        except ClientError as e:
            logger.error("Error getting cluster %s: %s", cluster_name, str(e))
            raise

    def get_node_group(
        self, node_group_name: str, cluster_name: Optional[str] = None
    ) -> Dict:
        """
        Retrieve node group information from EKS.

        Args:
            node_group_name: The name of the node group
            cluster_name: The name of the EKS cluster (optional)

        Returns:
            Dictionary containing node group information

        Raises:
            ClientError: If the AWS API request fails
        """
        cluster_name = cluster_name or self.cluster_name

        try:
            response = self.eks.describe_nodegroup(
                clusterName=cluster_name, nodegroupName=node_group_name
            )
            # Serialize the response to handle datetime objects
            return self._serialize_aws_response(response["nodegroup"])
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.error(
                    "Node group '%s' not found in cluster '%s'",
                    node_group_name,
                    cluster_name,
                )
            else:
                logger.error("Failed to get node group '%s': %s", node_group_name, e)
            raise

    def create_node_group(
        self,
        node_group_name: str,
        instance_type: str,
        node_count: int = 0,
        gpu_node_group: bool = False,
        capacity_type: str = "ON_DEMAND",
    ) -> Any:
        """
        Create a new node group in the EKS cluster.

        Args:
            node_group_name: The name for the new node group
            instance_type: EC2 instance type for the node (e.g., 't3.medium')
            node_count: The number of nodes to create (default: 0)
            cluster_name: The name of the EKS cluster (optional)
            gpu_node_group: Whether this is a GPU-enabled node group (default: False)
            capacity_type: Capacity type (ON_DEMAND or SPOT, default: ON_DEMAND)

        Returns:
            The created node group object

        Raises:
            ValueError: If required parameters are missing
            ClientError: If the AWS API request fails
        """
        self.vm_size = instance_type  # Set for operation tracking

        # Prepare operation metadata
        metadata = {
            "cluster_name": self.cluster_name,
            "vm_size": instance_type,
            "node_count": node_count,
            "gpu_node_group": gpu_node_group,
            "capacity_type": capacity_type,
        }

        # Start operation tracking
        with self._get_operation_context()(
            "create_node_pool", "aws", metadata, result_dir=self.result_dir
        ) as op:
            try:
                logger.info(
                    "Creating node group '%s' with %s nodes", node_group_name, node_count
                )
                logger.info("Instance types: %s", instance_type)
                logger.info("Capacity type: %s", capacity_type)

                # Prepare node group creation parameters
                # instanceTypes will be added to launch template
                create_params = {
                    "clusterName": self.cluster_name,
                    "nodegroupName": node_group_name,
                    "scalingConfig": {
                        "minSize": node_count,
                        "maxSize": node_count
                        + 1,  # AWS requires maxSize to be atleast 1
                        "desiredSize": node_count,
                    },
                    "subnets": self.subnets,
                    "capacityType": capacity_type,
                    "nodeRole": self.node_role_arn,
                    "amiType": self.get_ami_type_with_k8s_version(gpu_node_group=gpu_node_group),
                    "labels": {
                        "cluster-name": self.cluster_name,
                        "nodegroup-name": node_group_name,
                        "run_id": self.run_id,
                        "scenario": f"{get_env_vars('SCENARIO_TYPE')}-{get_env_vars('SCENARIO_NAME')}",
                    },
                }
                logger.info(
                    "Creating launch template for node group '%s'", node_group_name
                )

                # Check for capacity reservation if requested
                reservation_id = None
                if capacity_type == "CAPACITY_BLOCK":
                    logger.info(
                        "Checking for capacity reservation for node group '%s'", node_group_name
                    )

                    res_id = self._get_capacity_reservation_id(
                        instance_type=instance_type,
                        count=node_count,
                        availability_zones=self.subnet_azs,
                    )

                    if res_id:
                        reservation_id = res_id
                        logger.info(
                            "Found capacity reservation %s in AZ %s", reservation_id, self.subnet_azs
                        )

                try:
                    launch_template = self._create_launch_template(
                        node_group_name=node_group_name,
                        instance_type=instance_type,
                        reservation_id=reservation_id,  # Will be None if not found
                        gpu_node_group=gpu_node_group,
                        capacity_type=capacity_type,
                    )

                    # Add launch template to node group creation parameters
                    create_params["launchTemplate"] = {
                        "id": launch_template["id"],
                        "version": str(launch_template["version"]),
                    }

                    if reservation_id:
                        op.add_metadata("capacity_reservation_id", reservation_id)
                    op.add_metadata("launch_template_id", launch_template["id"])

                    if reservation_id:
                        logger.info(
                            "Using launch template %s with capacity reservation %s",
                            launch_template["id"],
                            reservation_id,
                        )
                    else:
                        logger.info(
                            "Using launch template %s",
                            launch_template["id"],
                        )
                except Exception as e:
                    logger.error("Failed to create launch template: %s", e)
                    raise Exception(f"Failed to create launch template: {str(e)}") from e

                # Create the node group with the parameters
                response = self.eks.create_nodegroup(**create_params)

                self._wait_for_node_group_active(node_group_name, self.cluster_name)
                node_group = response["nodegroup"]

                logger.info(
                    "Node group creation initiated. Status: %s", node_group['status']
                )
                label_selector = f"nodegroup-name={node_group_name}"

                # Wait for nodes to be ready
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                    label_selector=label_selector,
                )

                logger.info(
                    "All %s nodes in node group '%s' are ready", len(ready_nodes), node_group_name
                )

                # Verify NVIDIA drivers if this is a GPU node pool
                pod_logs = None
                if gpu_node_group and node_count > 0:
                    logger.info(
                        "Verifying NVIDIA drivers for GPU node pool '%s'", node_group_name
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                    op.add_metadata("nvidia_driver_logs", pod_logs)

                # Add additional metadata
                op.add_metadata("ready_nodes", len(ready_nodes) if ready_nodes else 0)
                op.add_metadata("node_pool_name", node_group_name)
                op.add_metadata(
                    "nodepool_info",
                    self.get_node_group(node_group_name, self.cluster_name),
                )
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(self.cluster_name)
                )
                return True

            except Exception as e:
                # Log the error
                error_msg = str(e)
                logger.error(
                    "Error creating node pool %s: %s", node_group_name, error_msg
                )
                # The OperationContext will automatically record failure when exiting
                raise

    def scale_node_group(
        self,
        node_group_name: str,
        node_count: int,
        cluster_name: Optional[str] = None,
        gpu_node_group: bool = False,
        progressive: bool = False,
        scale_step_size: int = 1,
    ) -> Dict:
        """
        Scale a node group to the specified node count.

        Args:
            node_group_name: The name of the node group
            node_count: The desired number of nodes
            cluster_name: The name of the EKS cluster (optional)
            gpu_node_group: Whether this is a GPU-enabled node group (default: False)
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)

        Returns:
            The scaled node group object

        Raises:
            ClientError: If the AWS API request fails
        """
        cluster_name = cluster_name or self.cluster_name

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "node_count": node_count,
            "gpu_node_group": gpu_node_group,
            "progressive_scaling": progressive,
            "scale_step_size": scale_step_size,
        }

        # Get current node group state
        current_node_group = self.get_node_group(node_group_name, cluster_name)
        current_count = current_node_group["scalingConfig"]["desiredSize"]
        operation_type = "scale"
        if node_count > current_count:
            operation_type = "scale_up"
        elif node_count < current_count:
            operation_type = "scale_down"
        else:
            # No change in node count, return the node pool as is
            logger.info(
                "Node pool %s already has %s nodes. No scaling needed.", node_group_name, node_count
            )
        logger.info(
            "Scaling node group '%s' from %s to %s nodes", node_group_name, current_count, node_count
        )

        if progressive and abs(node_count - current_count) > scale_step_size:
            return self._progressive_scale(
                node_group_name,
                current_count,
                node_count,
                scale_step_size,
                cluster_name,
                metadata,
                operation_type,
                gpu_node_group,
            )

        with self._get_operation_context()(
            operation_type, "aws", metadata, result_dir=self.result_dir
        ) as op:
            try:
                scaling_config = current_node_group["scalingConfig"].copy()
                scaling_config["desiredSize"] = node_count

                # Ensure maxSize is at least the target count
                if scaling_config["maxSize"] < node_count:
                    scaling_config["maxSize"] = node_count
                    logger.info("Updating maxSize to %d", node_count)
                op.name = operation_type
                op.add_metadata("vm_size", self.vm_size)
                op.add_metadata("current_count", current_count)

                update_config = {
                    "clusterName": cluster_name,
                    "nodegroupName": node_group_name,
                    "scalingConfig": scaling_config,
                }

                # Update the node group
                try:
                    self.eks.update_nodegroup_config(**update_config)
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.error(
                            "Node group '%s' not found in cluster '%s'", node_group_name, cluster_name
                        )
                    else:
                        logger.error(
                            "Failed to update node group '%s': %s", node_group_name, e
                        )
                    raise

                logger.info(
                    "Scaling operation initiated for node group '%s'", node_group_name
                )

                # Wait for the scaling operation to complete
                self._wait_for_node_group_active(node_group_name, cluster_name)
                label_selector = f"nodegroup-name={node_group_name}"
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                    label_selector=label_selector,
                )

                op.add_metadata("ready_nodes", len(ready_nodes) if ready_nodes else 0)
                op.add_metadata("node_pool_name", node_group_name)
                op.add_metadata(
                    "nodepool_info",
                    self.get_node_group(node_group_name, self.cluster_name),
                )
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(self.cluster_name)
                )

                logger.info(
                    "Node group '%s' scaled successfully to %s nodes", node_group_name, node_count
                )

                pod_logs = None
                # Verify NVIDIA drivers only for GPU node pools during scale-up operations
                # and only when reaching the final target (not intermediate steps)
                if gpu_node_group and operation_type == "scale_up" and node_count > 0:
                    logger.info(
                        "Verifying NVIDIA drivers for GPU node pool '%s' after reaching final target", node_group_name
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                    op.add_metadata("nvidia_driver_logs", pod_logs)

                return True

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    "Error scaling node pool %s: %s", node_group_name, error_msg
                )
                # The OperationContext will automatically record failure when exiting
                raise

    def delete_node_group(
        self, node_group_name: str, cluster_name: Optional[str] = None
    ) -> bool:
        """
        Delete a node group from the EKS cluster.

        Args:
            node_group_name: The name of the node group to delete
            cluster_name: The name of the EKS cluster (optional)

        Returns:
            True if deletion was successful

        Raises:
            ClientError: If the AWS API request fails
        """
        cluster_name = cluster_name or self.cluster_name

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "node_group_name": node_group_name,
        }

        # Try to get node group info before deletion for metadata
        try:
            node_group = self.get_node_group(node_group_name, cluster_name)
            metadata["instance_types"] = self.vm_size
            metadata["node_count"] = node_group["scalingConfig"]["desiredSize"]
            metadata["ami_type"] = node_group.get("amiType")
        except Exception as e:
            logger.warning(
                "Could not retrieve node group '%s' info before deletion: %s", node_group_name, e
            )

        with self._get_operation_context()(
            "delete_node_pool", "aws", metadata, result_dir=self.result_dir
        ) as op:
            try:
                logger.info("Deleting node group '%s'", node_group_name)
                op.add_metadata("node_pool_name", node_group_name)
                op.add_metadata("vm_size", self.vm_size)
                op.add_metadata(
                    "nodepool_info",
                    self.get_node_group(node_group_name, self.cluster_name),
                )
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(self.cluster_name)
                )

                if hasattr(self, "launch_template_id") and self.launch_template_id:
                    # If a launch template was created, delete it
                    logger.info(
                        "Deleting launch template %s for node group %s", self.launch_template_id, node_group_name
                    )
                    self._delete_launch_template()

                self.eks.delete_nodegroup(
                    clusterName=cluster_name, nodegroupName=node_group_name
                )

                logger.info("Deletion initiated for node group '%s'", node_group_name)

                # Wait for the node group to be deleted
                self._wait_for_node_group_deleted(node_group_name, cluster_name)

                logger.info("Node group '%s' deleted successfully", node_group_name)
                return True

            except Exception as e:
                logger.error("Failed to delete node group '%s': %s", node_group_name, e)
                raise

    def _progressive_scale(
        self,
        node_group_name: str,
        current_count: int,
        target_count: int,
        step_size: int,
        cluster_name: str,
        base_metadata: Dict,
        operation_type: str,
        gpu_node_group: bool = False,
    ) -> Dict:
        """
        Progressively scale a node group in steps.

        Args:
            node_group_name: The name of the node group
            current_count: Current number of nodes
            target_count: Target number of nodes
            step_size: Number of nodes to add/remove in each step
            cluster_name: The name of the EKS cluster
            base_metadata: Base metadata for operation tracking
            operation_type: Type of scaling operation (scale_up, scale_down)
            gpu_node_group: Whether this is a GPU-enabled node group

        Returns:
            The final node group object
        """
        logger.info(
            "Progressive scaling from %s to %s nodes in steps of %s", current_count, target_count, step_size
        )

        metadata = base_metadata.copy()
        metadata["progressive_scaling"] = True
        with self._get_operation_context()(
            operation_type, "aws", metadata, result_dir=self.result_dir
        ) as op:
            try:
                steps = []
                if target_count > current_count:
                    # Scaling up
                    for count in range(
                        current_count + step_size, target_count + 1, step_size
                    ):
                        steps.append(min(count, target_count))
                    if steps[-1] != target_count:
                        steps.append(target_count)
                else:
                    # Scaling down
                    for count in range(
                        current_count - step_size, target_count - 1, -step_size
                    ):
                        steps.append(max(count, target_count))
                    if steps[-1] != target_count:
                        steps.append(target_count)

                logger.info(
                    "Progressive scaling steps: %s -> %s", current_count, ' -> '.join(map(str, steps))
                )

                current_node_group = None
                label_selector = f"nodegroup-name={node_group_name}"
                for i, step_count in enumerate(steps):
                    logger.info(
                        "Progressive scaling step %s/%s: scaling to %s nodes", i + 1, len(steps), step_count
                    )

                    # Scale to this step
                    current_node_group = self.scale_node_group(
                        node_group_name=node_group_name,
                        node_count=step_count,
                        cluster_name=cluster_name,
                        progressive=False,  # Avoid recursive progressive scaling
                        gpu_node_group=gpu_node_group,
                    )

                    ready_nodes = self.k8s_client.wait_for_nodes_ready(
                        node_count=step_count,
                        operation_timeout_in_minutes=self.operation_timeout_minutes,
                        label_selector=label_selector,
                    )

                    # Small delay between steps
                    if i < len(steps) - 1:
                        time.sleep(10)

                    op.add_metadata("vm_size", self.vm_size)
                    op.add_metadata(
                        "ready_nodes", len(ready_nodes) if ready_nodes else 0
                    )

                    op.add_metadata(
                    "nodepool_info",
                    self.get_node_group(node_group_name, self.cluster_name))
                    op.add_metadata(
                        "cluster_info", self.get_cluster_data(self.cluster_name)
                    )

                logger.info(
                    "Progressive scaling completed. Final count: %s", target_count
                )
                return current_node_group

            except Exception as e:
                logger.error("Progressive scaling failed: %s", e)
                raise

    def _wait_for_node_group_active(self, node_group_name: str, cluster_name: str):
        """
        Wait for a node group to become active.

        Args:
            node_group_name: The name of the node group
            cluster_name: The name of the EKS cluster

        Raises:
            WaiterError: If the waiter times out or encounters an error
        """
        logger.info("Waiting for node group '%s' to become active...", node_group_name)

        try:
            waiter = self.eks.get_waiter("nodegroup_active")
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=node_group_name,
                WaiterConfig={
                    "Delay": 30,  # Check every 30 seconds
                    "MaxAttempts": int(
                        self.operation_timeout_minutes * 2
                    ),  # 2 attempts per minute
                },
            )
            logger.info("Node group '%s' is now active", node_group_name)
        except WaiterError as e:
            logger.error(
                "Timeout waiting for node group '%s' to become active: %s", node_group_name, e
            )
            raise

    def _wait_for_node_group_deleted(self, node_group_name: str, cluster_name: str):
        """
        Wait for a node group to be deleted.

        Args:
            node_group_name: The name of the node group
            cluster_name: The name of the EKS cluster

        Raises:
            WaiterError: If the waiter times out or encounters an error
        """
        logger.info("Waiting for node group '%s' to be deleted...", node_group_name)

        try:
            waiter = self.eks.get_waiter("nodegroup_deleted")
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=node_group_name,
                WaiterConfig={
                    "Delay": 30,  # Check every 30 seconds
                    "MaxAttempts": int(
                        self.operation_timeout_minutes * 2
                    ),  # 2 attempts per minute
                },
            )
            logger.info("Node group '%s' has been deleted", node_group_name)
        except WaiterError as e:
            logger.error(
                "Timeout waiting for node group '%s' to be deleted: %s", node_group_name, e
            )
            raise

    def _get_capacity_reservation_id(
        self, instance_type: str, count: int, availability_zones: List
    ) -> Optional[str]:
        """
        Find an existing capacity reservation for the specified instance type.

        Args:
            instance_type: EC2 instance type to look for
            count: Number of instances needed (used for logging only)
            availability_zones: List of AZ's where to look for the reservation

        Returns:
            The ID of the capacity reservation or None if not found
        """
        try:
            # First, try to find a reservation with our run_id tag
            logger.info(
                "Looking for capacity reservations for %s in %s", instance_type, availability_zones
            )

            response = self.ec2.describe_capacity_reservations(
                Filters=[
                    {"Name": "instance-type", "Values": [instance_type]},
                    {"Name": "availability-zone", "Values": availability_zones},
                    {"Name": "state", "Values": ["active"]},
                ]
            )

            run_id_reservations = response.get("CapacityReservations", [])

            if run_id_reservations:
                reservation = run_id_reservations[0]
                reservation_id = reservation["CapacityReservationId"]
                current_count = reservation["TotalInstanceCount"]
                available_count = reservation["AvailableInstanceCount"]

                logger.info(
                    "Found existing capacity reservation with matching run_id: %s with %s available instances out of %s total", 
                    reservation_id, available_count, current_count
                )

                if available_count < count:
                    logger.warning(
                        "Capacity reservation has only %s instances available, but %s were requested", 
                        available_count, count
                    )

                return reservation_id

            # No existing reservation found
            logger.error(
                "No existing capacity reservation found for %s in %s", instance_type, availability_zones
            )
            return None

        except Exception as e:
            logger.error("Failed to find capacity reservation: %s", str(e))
            return None

    def _create_default_launch_template(
        self,
        name: str,
        instance_type: str,
        node_group_name: str,
        gpu_node_group: bool = False,
        capacity_type: str = "ON_DEMAND",
        reservation_id: Optional[str] = None,
    ) -> str:
        """
        Creates a launch template with standard configuration and all necessary tags.

        Args:
            name: Name of the launch template
            instance_type: EC2 instance type
            node_group_name: Name of the node group this template is for
            gpu_node_group: Whether this is for a GPU node group
            capacity_type: Capacity type (ON_DEMAND, SPOT, CAPACITY_BLOCK)
            reservation_id: Optional capacity reservation ID

        Returns:
            The ID of the created launch template
        """
        try:
            logger.info(
                "Creating launch template '%s' for node group '%s'", name, node_group_name
            )
            # Prepare launch template data
            launch_template_data = {}
            launch_template_data["InstanceType"] = instance_type
            # Add capacity reservation configuration if provided
            # we can only 1 capacity reservation per launch template
            # Adding Capacity Block reservations to a resource group is not supported.
            if reservation_id and capacity_type == "CAPACITY_BLOCK":
                logger.info(
                    "Adding capacity reservation %s to launch template", reservation_id
                )

                launch_template_data["InstanceMarketOptions"] = {
                    "MarketType": "capacity-block"
                }
                launch_template_data["CapacityReservationSpecification"] = {
                    "CapacityReservationTarget": {
                        "CapacityReservationId": reservation_id
                    }
                }

            # Get additional tags for the launch template
            scenario_name = os.environ.get("SCENARIO_NAME", "unknown")
            scenario_type = os.environ.get("SCENARIO_TYPE", "unknown")
            deletion_due_time_env = os.environ.get("DELETION_DUE_TIME")
            if deletion_due_time_env:
                deletion_due_time = deletion_due_time_env
            else:
                deletion_due_time = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Prepare standard tags
            tags = [
                {"Key": "Name", "Value": name},
                {"Key": "run_id", "Value": self.run_id},
                {"Key": "cluster_name", "Value": self.cluster_name},
                {"Key": "node_group_name", "Value": node_group_name},
                {"Key": "gpu_node_group", "Value": str(gpu_node_group)},
                {"Key": "instance_type", "Value": instance_type},
                {"Key": "capacity_type", "Value": capacity_type},
                {
                    "Key": "scenario_name",
                    "Value": scenario_name,
                },
                {
                    "Key": "scenario_type",
                    "Value": scenario_type,
                },
                {
                    "Key": "created_at",
                    "Value": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                {
                    "Key": "deletion_due_time",
                    "Value": deletion_due_time,
                },
            ]

            # Add capacity reservation tag if applicable
            if reservation_id:
                tags.append({"Key": "capacity_reservation_id", "Value": reservation_id})

            # Create launch template with comprehensive tags
            response = self.ec2.create_launch_template(
                LaunchTemplateName=name,
                VersionDescription=f"Template for {instance_type} node group {node_group_name}"
                + (f" with reservation {reservation_id}" if reservation_id else ""),
                TagSpecifications=[
                    {
                        "ResourceType": "launch-template",
                        "Tags": tags,
                    },
                ],
                LaunchTemplateData=launch_template_data,
            )

            launch_template_id = response["LaunchTemplate"]["LaunchTemplateId"]
            logger.info(
                "Created launch template ID: %s for node group %s", launch_template_id, node_group_name
            )
            self.launch_template_id = launch_template_id
            return launch_template_id

        except Exception as e:
            logger.error(
                "Failed to create launch template for node group %s: %s", node_group_name, str(e)
            )
            raise

    def _create_launch_template(
        self,
        node_group_name: str,
        instance_type: str,
        reservation_id: Optional[str] = None,
        gpu_node_group: bool = False,
        capacity_type: str = "ON_DEMAND",
    ) -> Dict:
        """
        Creates a launch template with standard configuration and optional capacity reservation.

        Args:
            node_group_name: Name of the node group
            instance_type: EC2 instance type
            reservation_id: Optional capacity reservation ID to use
            gpu_node_group: Whether this is for a GPU node group
            capacity_type: Capacity type (ON_DEMAND, SPOT, CAPACITY_BLOCK)

        Returns:
            Dictionary with launch template ID and version
        """
        # Generate a unique but consistent name for the launch template
        template_name = f"{self.cluster_name}-{node_group_name}-{instance_type}"
        template_name = template_name[:128]  # AWS has a limit of 128 chars for names

        try:
            # Create launch template using the default method with all tags
            launch_template_id = self._create_default_launch_template(
                name=template_name,
                instance_type=instance_type,
                node_group_name=node_group_name,
                gpu_node_group=gpu_node_group,
                capacity_type=capacity_type,
                reservation_id=reservation_id,  # Will be None if no reservation found
            )

            return {
                "id": launch_template_id,
                "version": 1,  # New templates start with version 1
            }

        except Exception as e:
            logger.error(
                "Error creating launch template for node group %s: %s", node_group_name, str(e)
            )
            sys.exit(1)

    def _delete_launch_template(self) -> bool:
        """
        Deletes a launch template by ID.

        Args:
            launch_template_id: The ID of the launch template to delete

        Returns:
            True if deletion was successful

        Raises:
            ClientError: If the AWS API request fails
        """
        try:
            logger.info("Deleting launch template %s", self.launch_template_id)
            self.ec2.delete_launch_template(LaunchTemplateId=self.launch_template_id)
            logger.info(
                "Launch template %s deleted successfully", self.launch_template_id
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to delete launch template %s: %s", self.launch_template_id, str(e)
            )
            raise

    def get_ami_type_with_k8s_version(
        self, gpu_node_group: bool = False,
    ) -> str:
        """
        Get the appropriate AMI type based on the Kubernetes version and whether it's a GPU node group.

        Args:
            gpu_node_group: Whether this is a GPU-enabled node group (default: False)

        Returns:
            The AMI type string

        Raises:
            ValueError: If k8s_version is None or cannot be parsed
        """
        if self.k8s_version is None:
            raise ValueError("Kubernetes version is not set. Cannot determine AMI type.")

        try:
            logger.info("Determining AMI type for Kubernetes version: %s", self.k8s_version)

            # Normalize version for semver comparison
            # Strip 'v' prefix if present and ensure it has .0 suffix for proper semver
            clean_version = self.k8s_version.lstrip('v')
            if '.' not in clean_version or len(clean_version.split('.')) == 2:
                clean_version = f"{clean_version}.0"
            
            # Use semver to compare with 1.33.0
            current_semver = semver.Version.parse(clean_version)
            threshold_semver = semver.Version.parse("1.33.0")
            
            if current_semver < threshold_semver:  # Current version < 1.33
                # For Kubernetes versions < 1.33, use AL2_x86_64 for non-GPU and AL2_x86_64_GPU for GPU
                if gpu_node_group:
                    ami_type = "AL2_x86_64_GPU"
                else:
                    ami_type = "AL2_x86_64"
            else:  # Current version >= 1.33
                # For Kubernetes versions >= 1.33, use AL2023_x86_64_NVIDIA for GPU and AL2023_x86_64 for non-GPU
                if gpu_node_group:
                    ami_type = "AL2023_x86_64_NVIDIA"
                else:
                    ami_type = "AL2023_x86_64_STANDARD"

            logger.info("Selected AMI type: %s for k8s version %s (GPU: %s)",
                       ami_type, self.k8s_version, gpu_node_group)
            return ami_type

        except Exception as e:
            error_msg = f"Invalid Kubernetes version format '{self.k8s_version}': {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg) from e
