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
from typing import Dict, Optional, List, Any

# Third party imports
import boto3
from botocore.exceptions import ClientError, WaiterError

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
        from crud.operation import OperationContext # pylint: disable=import-outside-toplevel

        return OperationContext

    def __init__(
        self,
        region: Optional[str] = None,
        kube_config_file: Optional[str] = os.path.expanduser("~/.kube/config"),
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
        # self.cluster_name = self.__get_cluster_name(run_id)
        self.region = region or get_env_vars("AWS_DEFAULT_REGION")
        self.kube_config_file = kube_config_file
        self.result_dir = result_dir
        self.operation_timeout_minutes = operation_timeout_minutes

        try:
            self.eks = boto3.client('eks', region_name=self.region)
            # Initialize the EC2 client for the VPC configuration
            self.ec2 = boto3.client('ec2', region_name=self.region)
            # Initialize the IAM client for the role ARN
            self.iam = boto3.client('iam', region_name=self.region)
            self.run_id = get_env_vars("RUN_ID")
            self.cluster_name = self._get_cluster_name_by_run_id(self.run_id)
            logger.info(f"Successfully connected to AWS EKS. Found cluster: {self.cluster_name}")
            self._load_subnet_ids()
            self._load_node_role_arn()

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise

        # Initialize Kubernetes client if provided or if kubeconfig is available
        try:
            self.k8s_client = KubernetesClient(config_file=kube_config_file)
            logger.info("Kubernetes client initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {str(e)}")
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
            logger.info(f"Checking {len(all_clusters)} clusters for run_id = {run_id}")

            for cluster_name in all_clusters:
                details = self.eks.describe_cluster(name=cluster_name)
                tags = details["cluster"].get("tags", {})

                if tags.get("run_id") == run_id:
                    logger.info(f"Matched cluster: {cluster_name} with run_id: {run_id}")
                    return cluster_name
            raise Exception(f"No EKS cluster found with run_id: {run_id}")
        except Exception as e:
            logger.error(f"Error while getting EKS clusters : {e}")
            raise

    def _load_subnet_ids(self):
        """
        Loads the subnet IDs based on the run ID.

        Raises:
            Exception: If no subnets are found with the given run ID.
        """
        response = self.ec2.describe_subnets(Filters=[
            {'Name': 'tag:run_id', 'Values': [self.run_id]},
        ])
        logger.debug(response)
        self.subnets = [subnet['SubnetId'] for subnet in response['Subnets']]
        logger.info("Subnets: %s", self.subnets)
        if self.subnets == []:
            raise Exception("No subnets found for run_id: " + self.run_id)

    def _load_node_role_arn(self):
        """
        Loads the node role ARN based on the run ID.

        Raises:
            Exception: If no role is found with the given run ID.
        """
        response = self.iam.list_roles(
            MaxItems=100,
        )
        roles = response['Roles']
        while response.get('Marker'):
            logger.info(response['Marker'])
            response = self.iam.list_roles(
                MaxItems=100,
                Marker=response['Marker']
            )
            roles.extend(response['Roles'])
        logger.debug("All the roles: %s", roles)
        for role in roles:
            if role['RoleName'].startswith('terraform'):
                role_tags = self.iam.list_role_tags(RoleName=role['RoleName'])
                for tag in role_tags['Tags']:
                    if tag['Key'] == 'run_id' and tag['Value'] == self.run_id:
                        self.node_role_arn = role['Arn']
                        break
        if self.node_role_arn == "":
            raise Exception("No role found with run_id: " + self.run_id)

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
            cluster = response['cluster']
            
            # Convert the cluster object to a serializable dictionary
            cluster_data = (
                cluster.as_dict() if hasattr(cluster, "as_dict") else dict(cluster)
            )

            return cluster_data
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.error(
                    f"Cluster {cluster_name} not found in resource group {self.resource_group}"
                )
            else:
                logger.error(f"Error getting cluster {cluster_name}: {str(e)}")
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
        instance_type: str,
        node_count: int = 0,
        gpu_node_group: bool = False,
        capacity_type: str = "SPOT",
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
            "instance_type": instance_type,
            "node_count": node_count,
            "gpu_node_group": gpu_node_group,
            "capacity_type": capacity_type,
        }
       

        # Start operation tracking
        with self._get_operation_context()(
            "create_node_pool", "aws", metadata, result_dir=self.result_dir
        ) as op:
            try:
                logger.info(f"Creating node group '{node_group_name}' with {node_count} nodes")
                logger.info(f"Instance types: {instance_type}")

                response = self.eks.create_nodegroup(
                    clusterName=self.cluster_name,
                    nodegroupName=node_group_name,
                    scalingConfig={
                        'minSize': node_count,
                        'maxSize': node_count +2,
                        'desiredSize': node_count
                    },
                    subnets=self.subnets,
                    instanceTypes=[instance_type],
                    nodeRole=self.node_role_arn,
                    capacityType=capacity_type,
                    labels={
                        "cluster-name": self.cluster_name,
                        "nodegroup-name": node_group_name,
                        "run_id": self.run_id,
                        "scenario": f"{get_env_vars('SCENARIO_TYPE')}-{get_env_vars('SCENARIO_NAME')}",
                    }
                )
                waiter = self.eks.get_waiter('nodegroup_active')
                waiter.wait(
                    clusterName=self.cluster_name,
                    nodegroupName=node_group_name,
                    WaiterConfig={
                        'Delay': 1,
                        'MaxAttempts': 7200 # 2 hours
                    }
                )
                node_group = response['nodegroup']

                logger.info(f"Node group creation initiated. Status: {node_group['status']}")
                label_selector = f"nodegroup-name={node_group_name}"

                # Wait for nodes to be ready
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                   label_selector=label_selector,
                )

                logger.info(f"All {len(ready_nodes)} nodes in node group '{node_group_name}' are ready")
                
                # Verify NVIDIA drivers if this is a GPU node pool
                pod_logs = None
                if gpu_node_group and node_count > 0:
                    logger.info(
                        f"Verifying NVIDIA drivers for GPU node pool '{node_group_name}'"
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                    op.add_metadata("nvidia_driver_logs", pod_logs)

                # Add additional metadata
                op.add_metadata("ready_nodes", len(ready_nodes) if ready_nodes else 0)
                op.add_metadata("node_pool_name", node_group_name)
                # op.add_metadata(
                #     "nodepool_info",                   
                #         self.get_node_group(node_group_name, self.cluster_name),
                # )
                # op.add_metadata(
                #     "cluster_info", self.get_cluster_data(self.cluster_name)
                # )
                return True

            except Exception as e:
                # Log the error
                error_msg = str(e)
                logger.error(f"Error creating node pool {node_group_name}: {error_msg}")
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
        current_count = current_node_group['scalingConfig']['desiredSize']
        self.vm_size = current_node_group['instanceTypes'][0]  # Set for operation tracking
        operation_type = "scale"
        if node_count > current_count:
            operation_type = "scale_up"
        elif node_count < current_count:
            operation_type = "scale_down"
        else:
            # No change in node count, return the node pool as is
            logger.info(
                f"Node pool {node_group_name} already has {node_count} nodes. No scaling needed."
            )
        logger.info(f"Scaling node group '{node_group_name}' from {current_count} to {node_count} nodes")

        if progressive and abs(node_count - current_count) > scale_step_size:
            return self._progressive_scale(
                node_group_name, current_count, node_count, scale_step_size, cluster_name, metadata, operation_type
            )

        with self._get_operation_context()(
            operation_type, "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                scaling_config = current_node_group['scalingConfig'].copy()
                scaling_config['desiredSize'] = node_count
                
                # Ensure maxSize is at least the target count
                if scaling_config['maxSize'] < node_count:
                    scaling_config['maxSize'] = node_count
                    logger.info(f"Updating maxSize to {node_count}")

                self.eks.update_nodegroup_config(
                    clusterName=cluster_name,
                    nodegroupName=node_group_name,
                    scalingConfig=scaling_config
                )

                logger.info(f"Scaling operation initiated for node group '{node_group_name}'")

                # Wait for the scaling operation to complete
                self._wait_for_node_group_active(node_group_name, cluster_name)

                op.name = operation_type
                op.add_metadata("vm_size", self.vm_size)
                op.add_metadata("current_count", current_count)
                

                logger.info(f"Node group '{node_group_name}' scaled successfully to {node_count} nodes")
                return True

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error scaling node pool {node_group_name}: {error_msg}")
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
            self.vm_size = node_group['instanceTypes'][0]
            metadata["instance_types"] = node_group['instanceTypes']
            metadata["node_count"] = node_group['scalingConfig']['desiredSize']
            metadata["ami_type"] = node_group.get('amiType')
        except ClientError:
            logger.warning(f"Could not retrieve node group '{node_group_name}' info before deletion")

        with self._get_operation_context()(
            "delete_node_group", "azure", metadata, result_dir=self.result_dir
        ) as operation:
            try:
                logger.info(f"Deleting node group '{node_group_name}'")

                self.eks.delete_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=node_group_name
                )

                logger.info(f"Deletion initiated for node group '{node_group_name}'")

                # Wait for the node group to be deleted
                self._wait_for_node_group_deleted(node_group_name, cluster_name)

                logger.info(f"Node group '{node_group_name}' deleted successfully")
                return True

            except Exception as e:
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
        operation_type: str
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

        metadata = base_metadata.copy()
        metadata["progressive_scaling"] = True
        with self._get_operation_context()(
            operation_type, "azure", metadata, result_dir=self.result_dir
        ) as op:
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
                label_selector = f"nodegroup-name={node_group_name}"
                for i, step_count in enumerate(steps):
                    logger.info(f"Progressive scaling step {i + 1}/{len(steps)}: scaling to {step_count} nodes")
                    
                    # Scale to this step
                    current_node_group = self.scale_node_group(
                        node_group_name=node_group_name,
                        node_count=step_count,
                        cluster_name=cluster_name,
                        progressive=False,  # Avoid recursive progressive scaling
                    )

                    ready_nodes = self.k8s_client.wait_for_nodes_ready(
                        node_count=step_count,
                        operation_timeout_in_minutes=self.operation_timeout_minutes,
                        label_selector=label_selector,
                    )

                    # Small delay between steps
                    if i < len(steps) - 1:
                        time.sleep(10)

                    op.add_metadata(
                        "ready_nodes", len(ready_nodes) if ready_nodes else 0
                    )

                logger.info(f"Progressive scaling completed. Final count: {target_count}")
                return current_node_group

            except Exception as e:
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
            waiter = self.eks.get_waiter('nodegroup_active')
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
            waiter = self.eks.get_waiter('nodegroup_deleted')
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
            response = self.eks.list_nodegroups(clusterName=self.cluster_name)
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
