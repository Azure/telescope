"""
AKS Client Module

This module provides a client for interacting with Azure Kubernetes Service (AKS),
focusing specifically on node pool operations (create, scale, delete).
It handles authentication with Azure services using Managed Identity
or other authentication methods provided by DefaultAzureCredential.

The client also validates node readiness after operations using Kubernetes API.

Operations are tracked using the Operation and OperationContext classes for metrics
and troubleshooting.
"""

import logging
import os
import time
from typing import Dict, Optional, Any

# Third party imports
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.core.pipeline.policies import RetryPolicy, RetryMode
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient

# Local imports
from utils.logger_config import get_logger, setup_logging
from utils.common import get_env_vars
from .kubernetes_client import KubernetesClient

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Suppress noisy Azure SDK logs
get_logger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
get_logger("azure.identity").setLevel(logging.ERROR)
get_logger("azure.core.pipeline").setLevel(logging.ERROR)
get_logger("msal").setLevel(logging.ERROR)


class AKSClient:
    """
    Client for Azure Kubernetes Service (AKS) operations.

    This client handles authentication with Azure services and provides
    methods for managing AKS node pools (create, scale, delete).
    It also validates node readiness using Kubernetes API.
    """

    def _get_operation_context(self):
        """
        Import and return the OperationContext class on demand to avoid circular imports.

        Returns:
            The OperationContext class
        """
        from crud.operation import OperationContext # pylint: disable=import-outside-toplevel

        return OperationContext

    def __init__(
        self,
        subscription_id: Optional[str] = None,
        resource_group: Optional[str] = None,
        cluster_name: Optional[str] = None,
        use_managed_identity: bool = False,
        kube_config_file: Optional[str] = os.path.expanduser("~/.kube/config"),
        result_dir: Optional[str] = None,
        operation_timeout_minutes: int = 10,  # Timeout for each step in seconds
    ):
        """
        Initialize the AKS client.

        Args:
            subscription_id: The Azure subscription ID. If not provided,
                             will try to get it from AZURE_MI_SUBSCRIPTION_ID env var.
            resource_group: The Azure resource group containing the AKS cluster.
            cluster_name: The name of the AKS cluster. If not provided,
                          will try to get the first cluster in the resource group.
            use_managed_identity: Whether to use managed identity for authentication.
                                 If False, will fall back to DefaultAzureCredential.
            kube_config_file: Path to the kubeconfig file for Kubernetes authentication.
        """
        # Get subscription ID from environment if not provided
        self.subscription_id = subscription_id or os.getenv("AZURE_SUBSCRIPTION_ID")
        if not self.subscription_id:
            raise ValueError(
                "Subscription ID is required. Provide it directly or set AZURE_SUBSCRIPTION_ID environment variable."
            )

        self.resource_group = resource_group
        self.cluster_name = cluster_name
        self.vm_size = None  # Initialize vm_size attribute

        # Set up authentication
        if use_managed_identity:
            mi_client_id = os.getenv("AZURE_MI_ID")
            if mi_client_id:
                logger.info("Using Managed Identity with client ID for authentication")
                self.credential = ManagedIdentityCredential(client_id=mi_client_id)
            else:
                logger.info("Using default Managed Identity for authentication")
                self.credential = ManagedIdentityCredential()
        else:
            logger.info("Using DefaultAzureCredential for authentication")
            self.credential = DefaultAzureCredential()
        # Set up retry policy
        retry_policy = RetryPolicy(
            retry_mode=RetryMode.Exponential,
            total=3,  # Maximum retry attempts
            backoff_factor=1.0,  # Exponential backoff factor
        )
        transport = RequestsTransport(retry_policy=retry_policy)
        # Initialize AKS client
        self.aks_client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
            transport=transport,
        )
        if not self.aks_client:
            error_msg = "Failed to initialize AKS client."
            logger.error(error_msg)
            raise ValueError(error_msg)
        self.result_dir = result_dir or get_env_vars("RESULT_DIR")
        self.operation_timeout_minutes = operation_timeout_minutes

        # Initialize Kubernetes client if provided or if kubeconfig is available
        try:
            self.k8s_client = KubernetesClient(config_file=kube_config_file)
            logger.info("Kubernetes client initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {str(e)}")
            self.k8s_client = None

        logger.info("AKS client initialized successfully")

    def get_cluster_name(self) -> str:
        """
        Get the AKS cluster name. If a cluster name was provided during initialization,
        returns that. Otherwise, finds the first cluster in the resource group.

        Returns:
            The name of the AKS cluster

        Raises:
            ValueError: If no cluster name was provided and no clusters found in resource group
        """
        if self.cluster_name:
            return self.cluster_name

        if not self.resource_group:
            raise ValueError("Resource group is required to get cluster name")

        try:
            # List clusters in the given resource group
            clusters = list(
                self.aks_client.managed_clusters.list_by_resource_group(
                    self.resource_group
                )
            )

            if clusters:
                self.cluster_name = clusters[0].name
                logger.info(f"Found AKS cluster: {self.cluster_name}")
                return self.cluster_name

            logger.error(
                f"No AKS clusters found in resource group: {self.resource_group}"
            )
            raise ValueError("No AKS clusters found in resource group")

        except HttpResponseError as e:
            logger.error(f"Error getting AKS clusters: {str(e)}")
            raise

    def get_cluster_data(self, cluster_name: Optional[str] = None) -> Dict:
        """
        Get detailed information about the AKS cluster.

        Args:
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.

        Returns:
            Dictionary containing cluster information

        Raises:
            ValueError: If resource group is not set or no cluster is found
            ResourceNotFoundError: If the cluster is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to get cluster data")

        cluster_name = cluster_name or self.get_cluster_name()

        try:
            cluster = self.aks_client.managed_clusters.get(
                resource_group_name=self.resource_group, resource_name=cluster_name
            )

            # Convert the cluster object to a serializable dictionary
            cluster_data = (
                cluster.as_dict() if hasattr(cluster, "as_dict") else dict(cluster)
            )

            return cluster_data

        except ResourceNotFoundError:
            logger.error(
                f"Cluster {cluster_name} not found in resource group {self.resource_group}"
            )
            raise
        except HttpResponseError as e:
            logger.error(f"Error getting cluster {cluster_name}: {str(e)}")
            raise

    def get_node_pool(
        self, node_pool_name: str, cluster_name: Optional[str] = None
    ) -> Any:
        """
        Get a specific node pool from the AKS cluster.

        Args:
            node_pool_name: The name of the node pool
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.

        Returns:
            Node pool object

        Raises:
            ValueError: If resource group is not set or no cluster is found
            ResourceNotFoundError: If the cluster or node pool is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to get node pools")

        cluster_name = cluster_name or self.get_cluster_name()

        try:
            node_pool = self.aks_client.agent_pools.get(
                resource_group_name=self.resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
            )
            logger.info(f"Successfully retrieved node pool {node_pool_name}")
            return node_pool
        except ResourceNotFoundError:
            logger.error(
                f"Node pool {node_pool_name} not found in cluster {cluster_name}"
            )
            raise
        except HttpResponseError as e:
            logger.error(f"Error getting node pool {node_pool_name}: {str(e)}")
            raise

    def create_node_pool(
        self,
        node_pool_name: str,
        vm_size: str,
        node_count: int = 0,
        cluster_name: Optional[str] = None,
        gpu_node_pool: bool = False,
    ) -> Any:
        """
        Create a new node pool in the AKS cluster.

        Args:
            node_pool_name: The name for the new node pool
            vm_size: The VM size for the nodes (e.g., 'Standard_DS2_v2')
            node_count: The number of nodes to create (default: 0)
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            The created node pool object or operation result

        Raises:
            ValueError: If resource_group is not set or no cluster is found
            ResourceNotFoundError: If the cluster is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to create node pool")

        cluster_name = cluster_name or self.get_cluster_name()
        self.vm_size = vm_size

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "vm_size": vm_size,
            "node_count": node_count,
            "gpu_node_pool": gpu_node_pool,
        }

        # Create operation context to track the operation
        with self._get_operation_context()(
            "create_node_pool", "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                # Build parameters for node pool creation
                parameters = {
                    "count": node_count,
                    "vm_size": vm_size,
                    "os_type": "Linux",
                    "mode": "User",
                    "os_disk_type": "Managed",
                    "gpu_profile": {
                        "driver": "None" if gpu_node_pool else "Install",
                    },
                }

                logger.info(
                    f"Creating node pool {node_pool_name} in cluster {cluster_name}"
                )

                # Create the node pool
                self.aks_client.agent_pools.begin_create_or_update(
                    resource_group_name=self.resource_group,
                    resource_name=cluster_name,
                    agent_pool_name=node_pool_name,
                    parameters=parameters,
                ).result()

                label_selector = f"agentpool={node_pool_name}"

                # Wait for nodes to be ready
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                    label_selector=label_selector,
                )

                logger.info(
                    f"All {node_count} nodes in pool {node_pool_name} are ready"
                )

                # Verify NVIDIA drivers if this is a GPU node pool
                pod_logs = None
                if gpu_node_pool and node_count > 0:
                    logger.info(
                        f"Verifying NVIDIA drivers for GPU node pool '{node_pool_name}'"
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                    op.add_metadata("nvidia_driver_logs", pod_logs)

                # Add additional metadata
                op.add_metadata("ready_nodes", len(ready_nodes) if ready_nodes else 0)
                op.add_metadata("node_pool_name", node_pool_name)
                op.add_metadata(
                    "nodepool_info",                   
                        self.get_node_pool(node_pool_name, cluster_name).as_dict(),
                )
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(cluster_name)
                )

                return True

            except Exception as e:
                # Log the error
                error_msg = str(e)
                logger.error(f"Error creating node pool {node_pool_name}: {error_msg}")
                # The OperationContext will automatically record failure when exiting
                raise

    def scale_node_pool(
        self,
        node_pool_name: str,
        node_count: int,
        cluster_name: Optional[str] = None,
        gpu_node_pool: bool = False,
        progressive: bool = False,
        scale_step_size: int = 1,
    ) -> Any:
        """
        Scale a node pool to the specified node count.

        Args:
            node_pool_name: The name of the node pool
            node_count: The desired number of nodes
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)

        Returns:
            The scaled node pool object

        Raises:
            ValueError: If resource_group is not set or no cluster is found
            ResourceNotFoundError: If the cluster or node pool is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to scale node pool")

        cluster_name = cluster_name or self.get_cluster_name()

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "node_count": node_count,
            "gpu_node_pool": gpu_node_pool,
            "progressive_scaling": progressive,
            "scale_step_size": scale_step_size,
        }
        node_pool = self.get_node_pool(node_pool_name, cluster_name)

        current_count = node_pool.count
        if node_count > current_count:
            operation_type = "scale_up"
        elif node_count < current_count:
            operation_type = "scale_down"
        else:
            # No change in node count, return the node pool as is
            logger.info(
                f"Node pool {node_pool_name} already has {node_count} nodes. No scaling needed."
            )
            return node_pool

        # If progressive scaling is requested
        if progressive:
            return self._progressive_scale(
                node_pool_name=node_pool_name,
                current_count=current_count,
                target_count=node_count,
                scale_step_size=scale_step_size,
                operation_type=operation_type,
                cluster_name=cluster_name,
                gpu_node_pool=gpu_node_pool,
                node_pool=node_pool,
            )

        # Create operation context to track the operation
        with self._get_operation_context()(
            operation_type, "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                # Store VM size for metrics
                self.vm_size = node_pool.vm_size
                op.name = operation_type
                op.add_metadata("vm_size", self.vm_size)
                op.add_metadata("current_count", current_count)
                op.add_metadata("node_pool_name", node_pool_name)
                op.add_metadata(
                    "nodepool_info",
                        self.get_node_pool(node_pool_name, cluster_name).as_dict()
                )
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(cluster_name)
                )

                # For direct scaling, update the node count
                node_pool.count = node_count

                logger.info(f"Scaling node pool {node_pool_name} to {node_count} nodes")
                self.aks_client.agent_pools.begin_create_or_update(
                    resource_group_name=self.resource_group,
                    resource_name=cluster_name,
                    agent_pool_name=node_pool_name,
                    parameters=node_pool,
                )

                logger.info(
                    f"Waiting for {node_count} nodes in pool {node_pool_name} to be ready..."
                )

                # Use agentpool=node_pool_name as default label if not specified
                label_selector = f"agentpool={node_pool_name}"

                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                    label_selector=label_selector,
                )
                logger.info(
                    f"All {node_count} nodes in pool {node_pool_name} are ready"
                )

                pod_logs = None
                # Verify NVIDIA drivers only for GPU node pools during scale-up operations
                # and only when reaching the final target (not intermediate steps)
                if gpu_node_pool and operation_type == "scale_up" and node_count > 0:
                    logger.info(
                        f"Verifying NVIDIA drivers for GPU node pool '{node_pool_name}' after reaching final target"
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                    op.add_metadata("nvidia_driver_logs", pod_logs)
                # Record node readiness info
                op.add_metadata("ready_nodes", len(ready_nodes))

                return True

            except Exception as k8s_err:
                error_msg = str(k8s_err)
                logger.error(f"Error scaling node pool {node_pool_name}: {error_msg}")
                # The OperationContext will automatically record failure when exiting
                raise

    def delete_node_pool(
        self, node_pool_name: str, cluster_name: Optional[str] = None
    ) -> bool:
        """
        Delete a node pool from the AKS cluster.

        Args:
            node_pool_name: The name of the node pool to delete
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.

        Returns:
            True if deletion was successful

        Raises:
            ValueError: If resource_group is not set or no cluster is found
            ResourceNotFoundError: If the cluster or node pool is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to delete node pool")

        cluster_name = cluster_name or self.get_cluster_name()

        # Prepare operation metadata
        metadata = {
            "cluster_name": cluster_name,
            "node_pool_name": node_pool_name,
        }

        # Try to get node pool info before deletion for metadata
        try:
            node_pool = self.get_node_pool(node_pool_name, cluster_name)
            self.vm_size = node_pool.vm_size
            metadata["vm_size"] = self.vm_size
            metadata["node_count"] = node_pool.count
        except Exception as e:
            logger.warning(f"Could not get node pool info before deletion: {str(e)}")
            self.vm_size = None
            metadata["vm_size"] = None

        # Create operation context to track the operation
        with self._get_operation_context()(
            "delete_node_pool", "azure", metadata, result_dir=self.result_dir
        ) as op:
            try:
                logger.info(
                    f"Deleting node pool {node_pool_name} from cluster {cluster_name}"
                )
                # Add node pool name to operation metadata
                op.add_metadata("node_pool_name", node_pool_name)
                op.add_metadata(
                    "cluster_info", self.get_cluster_data(cluster_name)
                )
                # Always use no-wait for the Azure operation
                operation = self.aks_client.agent_pools.begin_delete(
                    resource_group_name=self.resource_group,
                    resource_name=cluster_name,
                    agent_pool_name=node_pool_name,
                )

                logger.info("Waiting for node pool deletion to complete...")
                operation.result()  # Wait for completion
                logger.info(f"Node pool {node_pool_name} deleted successfully")

                return True

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error deleting node pool {node_pool_name}: {error_msg}")
                # The OperationContext will automatically record failure when exiting
                raise

    def _progressive_scale(
        self,
        node_pool_name: str,
        current_count: int,
        target_count: int,
        scale_step_size: int = 1,
        operation_type: str = "scale",
        cluster_name: Optional[str] = None,
        gpu_node_pool: bool = False,
        node_pool: Optional[Any] = None,
    ) -> Any:
        """
        Scale a node pool progressively with specified step size

        Args:
            node_pool_name: Name of the node pool
            current_count: Starting node count
            target_count: Final desired node count
            scale_step_size: Number of nodes to add/remove in each step (default: 1)
            operation_type: Type of scaling operation (scale_up or scale_down)
            cluster_name: The name of the AKS cluster
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)
            node_pool: The node pool object to use for scaling. If None, will fetch it.

        Returns:
            The final node pool object or False if scaling failed
        """

        # Determine if we're scaling up or down
        scaling_up = current_count < target_count
        operation_type = "scale_up" if scaling_up else "scale_down"

        logger.info(
            f"Starting progressive scaling for node pool '{node_pool_name}' from {current_count} to {target_count} nodes (step size: {scale_step_size})"
        )

        wait_time = 30  # Default wait time between scale steps

        # Calculate the steps
        if scaling_up:
            steps = range(
                current_count + scale_step_size, target_count + 1, scale_step_size
            )
        else:
            steps = range(
                current_count - scale_step_size, target_count - 1, -scale_step_size
            )

        # Ensure the final step is exactly the target count
        if steps and steps[-1] != target_count:
            steps = list(steps)
            if target_count not in steps:
                steps.append(target_count)

        # If there are no intermediate steps, just add the target directly
        if not steps:
            steps = [target_count]

        logger.info(f"Planned scaling steps: {list(steps)}")

        result = None
        completed_steps = []

        # Execute scaling operation for each step
        for step_index, step in enumerate(steps):
            previous_count = current_count if step_index == 0 else steps[step_index - 1]

            # Create step-specific metadata
            step_metadata = {
                "node_pool_name": node_pool_name,
                "current_count": previous_count,
                "target_count": step,
                "scale_step_size": scale_step_size,
                "cluster_name": cluster_name or self.get_cluster_name(),
                "gpu_node_pool": gpu_node_pool,
            }

            # Create operation context for this specific step
            with self._get_operation_context()(
                operation_type, "azure", step_metadata, result_dir=self.result_dir
            ) as op:
                logger.info(
                    f"Scaling from {previous_count} to {step} nodes (step {step_index + 1}/{len(steps)})"
                )

                try:
                    # Add additional metadata to this step's operation
                    op.add_metadata(
                        "nodepool_info",                      
                            self.get_node_pool(node_pool_name, cluster_name).as_dict()
                    )
                    op.add_metadata(
                        "cluster_info", self.get_cluster_data(cluster_name)
                    )
                    node_pool.count = step  # Update node count in the node pool object
                    result = self.aks_client.agent_pools.begin_create_or_update(
                        resource_group_name=self.resource_group,
                        resource_name=cluster_name,
                        agent_pool_name=node_pool_name,
                        parameters=node_pool,
                    )

                    # Use agentpool=node_pool_name as default label if not specified
                    label_selector = f"agentpool={node_pool_name}"

                    ready_nodes = self.k8s_client.wait_for_nodes_ready(
                        node_count=step,
                        operation_timeout_in_minutes=self.operation_timeout_minutes,
                        label_selector=label_selector,
                    )
                    logger.info(f"All {step} nodes in pool {node_pool_name} are ready")

                    if result is None:
                        logger.error(f"Progressive scaling failed at step {step}")
                        op.add_metadata("error", "Scaling operation returned None")
                        return None

                    op.add_metadata(
                        "ready_nodes", len(ready_nodes) if ready_nodes else 0
                    )

                    # Update our tracking of completed steps
                    completed_steps.append(step)

                    logger.info(
                        f"Step {step_index + 1}/{len(steps)}: {previous_count}→{step} nodes completed"
                    )

                    # Wait between steps if not the last step
                    if step != steps[-1] and wait_time > 0:
                        logger.info(
                            f"Waiting {wait_time}s before next scaling operation..."
                        )
                        time.sleep(wait_time)

                    if step == target_count:
                        # Verify NVIDIA drivers only for GPU node pools during scale-up operations
                        # and only when reaching the final target (not intermediate steps)
                        if gpu_node_pool and operation_type == "scale_up" and step > 0:
                            pod_logs = None
                            logger.info(
                                f"Verifying NVIDIA drivers for GPU node pool '{node_pool_name}' after reaching final target"
                            )
                            pod_logs = self.k8s_client.verify_nvidia_smi_on_node(
                                ready_nodes
                            )
                            op.add_metadata("nvidia_driver_logs", pod_logs)


                except Exception as e:
                    logger.error(f"Error at step {step}: {str(e)}")
                    op.add_metadata("error", str(e))
                    raise

        logger.info(
            f"Progressive scaling from {current_count} to {target_count} completed successfully"
        )

        # Return True on successful completion
        return True
