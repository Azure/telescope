"""
EKS Client Module

This module provides a client for interacting with Amazon Elastic Kubernetes Service (EKS),
focusing specifically on node group operations (create, scale, delete).
It handles authentication with AWS services using boto3.

The client also validates node readiness after operations using Kubernetes API.

Operations are tracked using the Operation and OperationContext classes for metrics
and troubleshooting.
"""

import logging
import os
import time
from typing import Dict, Optional, Any, List

# Third party imports
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, WaiterError

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
        from crud.operation import OperationContext
        return OperationContext(
            cloud_provider="aws",
            service="eks",
            resource_group=self.cluster_name,
            result_dir=self.result_dir,
        )

    def __init__(
        self,
        run_id: str,
        cluster_name: str,
        region: Optional[str] = None,
        kube_config_file: Optional[str] = None,
        result_dir: Optional[str] = None,
        operation_timeout_minutes: float = 20.0
    ):
        """
        Initialize the EKS client.

        Args:
            cluster_name: Name of the EKS cluster
            region: AWS region (if not provided, will use AWS_DEFAULT_REGION or us-east-2)
            kube_config_file: Path to the Kubernetes config file (optional)
            result_dir: Directory to store operation results (optional)
            operation_timeout_minutes: Maximum time to wait for operations (default: 20 minutes)
        """
        self.cluster_name = self.__get_cluster_name(run_id)
        self.region = region or get_env_vars("AWS_DEFAULT_REGION")
        self.kube_config_file = kube_config_file
        self.result_dir = result_dir
        self.operation_timeout_minutes = operation_timeout_minutes
        self.vm_size = None  # Will be set during operations for compatibility with operation tracking

        try:
            self.eks = boto3.client('eks', region_name=region)
            # Initialize the EC2 client for the VPC configuration
            self.ec2 = boto3.client('ec2', region_name=region)
            # Initialize the IAM client for the role ARN
            self.iam = boto3.client('iam', region_name=region)

        except Exception as e:
            logger.error(f"Failed to initialize EKS client: {e}")
            raise

        # Initialize Kubernetes client if config file is provided
        self.k8s_client = None
        if kube_config_file and os.path.exists(kube_config_file):
            try:
                self.k8s_client = KubernetesClient(config_file=kube_config_file)
                logger.info("Kubernetes client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Kubernetes client: {e}")

    def __get_cluster_name(self) -> str:
        """
        Get the cluster name based on the run ID.

        Raises:
            Exception: If no cluster is found with the given run ID.

        """
        next_token = ""
        clusters = self.eks.list_clusters(maxResults=100, nextToken=next_token)
        cluster_name = clusters['clusters']

        while clusters.get('nextToken'):
            clusters = self.eks.list_clusters(maxResults=100, nextToken=clusters['nextToken'])
            cluster_name.extend(clusters['clusters'])

        for name in cluster_name:
            logger.info("cluster name: %s", name)
            try:
                cluster = self.eks.describe_cluster(name=name)
                if cluster['cluster']['tags']['run_id'] == self.run_id:
                    return name
            except Exception as e:
                logger.error("Failed to describe cluster: %s", e)
                logger.info("Ignore the error, continue the next")
        if self.cluster_name == "":
            raise Exception("No cluster found with run_id: " + self.run_id)

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
            response = self.eks_client.describe_cluster(name=cluster_name)
            cluster = response['cluster']
            
            return {
                'name': cluster['name'],
                'status': cluster['status'],
                'version': cluster['version'],
                'endpoint': cluster['endpoint'],
                'roleArn': cluster['roleArn'],
                'resourcesVpcConfig': cluster['resourcesVpcConfig'],
                'region': self.region,
                'platformVersion': cluster.get('platformVersion'),
                'createdAt': cluster.get('createdAt'),
            }
        except ClientError as e:
            logger.error(f"Failed to get cluster data for '{cluster_name}': {e}")
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
            response = self.eks_client.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=node_group_name
            )
            return response['nodegroup']
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.error(f"Node group '{node_group_name}' not found in cluster '{cluster_name}'")
            else:
                logger.error(f"Failed to get node group '{node_group_name}': {e}")
            raise

    def create_node_group(
        self,
        node_group_name: str,
        instance_types: List[str],
        node_count: int = 0,
        cluster_name: Optional[str] = None,
        gpu_node_group: bool = False,
        subnet_ids: Optional[List[str]] = None,
        node_role_arn: Optional[str] = None,
        ami_type: Optional[str] = None,
        capacity_type: str = "ON_DEMAND",
        disk_size: int = 20,
        scaling_config: Optional[Dict] = None,
    ) -> Dict:
        """
        Create a new node group in the EKS cluster.

        Args:
            node_group_name: The name for the new node group
            instance_types: List of EC2 instance types for the nodes (e.g., ['t3.medium'])
            node_count: The number of nodes to create (default: 0)
            cluster_name: The name of the EKS cluster (optional)
            gpu_node_group: Whether this is a GPU-enabled node group (default: False)
            subnet_ids: List of subnet IDs for the node group (optional, will use cluster subnets if not provided)
            node_role_arn: IAM role ARN for the node group (optional, will try to find one if not provided)
            ami_type: AMI type for the nodes (optional, will use AL2_x86_64 or AL2_x86_64_GPU based on gpu_node_group)
            capacity_type: Capacity type (ON_DEMAND or SPOT, default: ON_DEMAND)
            disk_size: Root disk size in GB (default: 20)
            scaling_config: Custom scaling configuration (optional)

        Returns:
            The created node group object

        Raises:
            ValueError: If required parameters are missing
            ClientError: If the AWS API request fails
        """
        cluster_name = cluster_name or self.cluster_name
        self.vm_size = instance_types[0]  # Set for operation tracking

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "instance_types": instance_types,
            "node_count": node_count,
            "gpu_node_group": gpu_node_group,
            "capacity_type": capacity_type,
        }

        # Get cluster information to retrieve subnets and node role if not provided
        cluster_data = self.get_cluster_data(cluster_name)
        
        if not subnet_ids:
            subnet_ids = cluster_data['resourcesVpcConfig']['subnetIds']
            logger.info(f"Using cluster subnets: {subnet_ids}")

        if not node_role_arn:
            node_role_arn = self._get_node_role_arn()
            logger.info(f"Using node role: {node_role_arn}")

        if not ami_type:
            ami_type = "AL2_x86_64_GPU" if gpu_node_group else "AL2_x86_64"

        # Prepare scaling configuration
        if not scaling_config:
            scaling_config = {
                'minSize': 0,
                'maxSize': max(node_count * 2, 10),  # Allow scaling up to 2x initial size or 10, whichever is larger
                'desiredSize': node_count
            }

        # Start operation tracking
        operation_context = self._get_operation_context()
        with operation_context.track_operation("create_node_group", metadata) as operation:
            try:
                logger.info(f"Creating node group '{node_group_name}' with {node_count} nodes")
                logger.info(f"Instance types: {instance_types}, AMI type: {ami_type}")

                create_params = {
                    'clusterName': cluster_name,
                    'nodegroupName': node_group_name,
                    'scalingConfig': scaling_config,
                    'instanceTypes': instance_types,
                    'amiType': ami_type,
                    'nodeRole': node_role_arn,
                    'subnets': subnet_ids,
                    'capacityType': capacity_type,
                    'diskSize': disk_size,
                }

                # Add GPU-specific configurations if needed
                if gpu_node_group:
                    create_params['taints'] = [
                        {
                            'key': 'nvidia.com/gpu',
                            'value': 'true',
                            'effect': 'NO_SCHEDULE'
                        }
                    ]

                response = self.eks_client.create_nodegroup(**create_params)
                node_group = response['nodegroup']

                logger.info(f"Node group creation initiated. Status: {node_group['status']}")

                # Wait for the node group to become active
                self._wait_for_node_group_active(node_group_name, cluster_name)

                # Get the final node group state
                final_node_group = self.get_node_group(node_group_name, cluster_name)
                
                operation.add_metadata("final_status", final_node_group['status'])
                operation.add_metadata("actual_node_count", final_node_group['scalingConfig']['desiredSize'])

                logger.info(f"Node group '{node_group_name}' created successfully")
                return final_node_group

            except Exception as e:
                operation.mark_failed(str(e))
                logger.error(f"Failed to create node group '{node_group_name}': {e}")
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
        current_count = current_node_group['scalingConfig']['desiredSize']
        self.vm_size = current_node_group['instanceTypes'][0]  # Set for operation tracking

        logger.info(f"Scaling node group '{node_group_name}' from {current_count} to {node_count} nodes")

        if progressive and abs(node_count - current_count) > scale_step_size:
            return self._progressive_scale(
                node_group_name, current_count, node_count, scale_step_size, cluster_name, metadata
            )

        # Direct scaling
        operation_context = self._get_operation_context()
        with operation_context.track_operation("scale_node_group", metadata) as operation:
            try:
                scaling_config = current_node_group['scalingConfig'].copy()
                scaling_config['desiredSize'] = node_count
                
                # Ensure maxSize is at least the target count
                if scaling_config['maxSize'] < node_count:
                    scaling_config['maxSize'] = node_count
                    logger.info(f"Updating maxSize to {node_count}")

                self.eks_client.update_nodegroup_config(
                    clusterName=cluster_name,
                    nodegroupName=node_group_name,
                    scalingConfig=scaling_config
                )

                logger.info(f"Scaling operation initiated for node group '{node_group_name}'")

                # Wait for the scaling operation to complete
                self._wait_for_node_group_active(node_group_name, cluster_name)

                # Get the final node group state
                final_node_group = self.get_node_group(node_group_name, cluster_name)
                
                operation.add_metadata("final_status", final_node_group['status'])
                operation.add_metadata("actual_node_count", final_node_group['scalingConfig']['desiredSize'])

                logger.info(f"Node group '{node_group_name}' scaled successfully to {node_count} nodes")
                return final_node_group

            except Exception as e:
                operation.mark_failed(str(e))
                logger.error(f"Failed to scale node group '{node_group_name}': {e}")
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
            self.vm_size = node_group['instanceTypes'][0]
            metadata["instance_types"] = node_group['instanceTypes']
            metadata["node_count"] = node_group['scalingConfig']['desiredSize']
            metadata["ami_type"] = node_group.get('amiType')
        except ClientError:
            logger.warning(f"Could not retrieve node group '{node_group_name}' info before deletion")

        operation_context = self._get_operation_context()
        with operation_context.track_operation("delete_node_group", metadata) as operation:
            try:
                logger.info(f"Deleting node group '{node_group_name}'")

                self.eks_client.delete_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=node_group_name
                )

                logger.info(f"Deletion initiated for node group '{node_group_name}'")

                # Wait for the node group to be deleted
                self._wait_for_node_group_deleted(node_group_name, cluster_name)

                operation.add_metadata("final_status", "deleted")
                logger.info(f"Node group '{node_group_name}' deleted successfully")
                return True

            except Exception as e:
                operation.mark_failed(str(e))
                logger.error(f"Failed to delete node group '{node_group_name}': {e}")
                raise

    def _progressive_scale(
        self,
        node_group_name: str,
        current_count: int,
        target_count: int,
        step_size: int,
        cluster_name: str,
        base_metadata: Dict,
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

        Returns:
            The final node group object
        """
        logger.info(f"Progressive scaling from {current_count} to {target_count} nodes in steps of {step_size}")

        operation_context = self._get_operation_context()
        metadata = base_metadata.copy()
        metadata["progressive_scaling"] = True

        with operation_context.track_operation("progressive_scale", metadata) as operation:
            try:
                steps = []
                if target_count > current_count:
                    # Scaling up
                    for count in range(current_count + step_size, target_count + 1, step_size):
                        steps.append(min(count, target_count))
                    if steps[-1] != target_count:
                        steps.append(target_count)
                else:
                    # Scaling down
                    for count in range(current_count - step_size, target_count - 1, -step_size):
                        steps.append(max(count, target_count))
                    if steps[-1] != target_count:
                        steps.append(target_count)

                logger.info(f"Progressive scaling steps: {current_count} -> {' -> '.join(map(str, steps))}")

                current_node_group = None
                for i, step_count in enumerate(steps):
                    logger.info(f"Progressive scaling step {i + 1}/{len(steps)}: scaling to {step_count} nodes")
                    
                    # Scale to this step
                    current_node_group = self.scale_node_group(
                        node_group_name=node_group_name,
                        node_count=step_count,
                        cluster_name=cluster_name,
                        progressive=False,  # Avoid recursive progressive scaling
                    )

                    # Small delay between steps
                    if i < len(steps) - 1:
                        time.sleep(10)

                operation.add_metadata("scaling_steps", steps)
                operation.add_metadata("final_node_count", target_count)

                logger.info(f"Progressive scaling completed. Final count: {target_count}")
                return current_node_group

            except Exception as e:
                operation.mark_failed(str(e))
                logger.error(f"Progressive scaling failed: {e}")
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
        logger.info(f"Waiting for node group '{node_group_name}' to become active...")
        
        try:
            waiter = self.eks_client.get_waiter('nodegroup_active')
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=node_group_name,
                WaiterConfig={
                    'Delay': 30,  # Check every 30 seconds
                    'MaxAttempts': int(self.operation_timeout_minutes * 2)  # 2 attempts per minute
                }
            )
            logger.info(f"Node group '{node_group_name}' is now active")
        except WaiterError as e:
            logger.error(f"Timeout waiting for node group '{node_group_name}' to become active: {e}")
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
        logger.info(f"Waiting for node group '{node_group_name}' to be deleted...")
        
        try:
            waiter = self.eks_client.get_waiter('nodegroup_deleted')
            waiter.wait(
                clusterName=cluster_name,
                nodegroupName=node_group_name,
                WaiterConfig={
                    'Delay': 30,  # Check every 30 seconds
                    'MaxAttempts': int(self.operation_timeout_minutes * 2)  # 2 attempts per minute
                }
            )
            logger.info(f"Node group '{node_group_name}' has been deleted")
        except WaiterError as e:
            logger.error(f"Timeout waiting for node group '{node_group_name}' to be deleted: {e}")
            raise

    def _get_node_role_arn(self) -> str:
        """
        Get the IAM role ARN for EKS node groups.
        
        This method tries to find an existing node group role or falls back to a default pattern.
        
        Returns:
            IAM role ARN for the node group
            
        Raises:
            ValueError: If no suitable role is found
        """
        try:
            # Try to find existing node groups to get the role pattern
            response = self.eks_client.list_nodegroups(clusterName=self.cluster_name)
            if response['nodegroups']:
                # Get the first node group's role as template
                first_ng = response['nodegroups'][0]
                ng_info = self.get_node_group(first_ng)
                return ng_info['nodeRole']
        except Exception as e:
            logger.warning(f"Could not find existing node group role: {e}")

        # Fall back to common role naming patterns
        account_id = self.session.client('sts').get_caller_identity()['Account']
        possible_roles = [
            f"arn:aws:iam::{account_id}:role/NodeInstanceRole",
            f"arn:aws:iam::{account_id}:role/EKSNodeGroupRole",
            f"arn:aws:iam::{account_id}:role/{self.cluster_name}-node-group-role",
            f"arn:aws:iam::{account_id}:role/eks-node-group-role",
        ]

        iam_client = self.session.client('iam')
        for role_arn in possible_roles:
            role_name = role_arn.split('/')[-1]
            try:
                iam_client.get_role(RoleName=role_name)
                logger.info(f"Found node group role: {role_arn}")
                return role_arn
            except ClientError:
                continue

        raise ValueError(
            f"Could not find a suitable IAM role for node groups. "
            f"Please ensure an IAM role exists with the necessary EKS node group permissions. "
            f"Tried: {possible_roles}"
        )
