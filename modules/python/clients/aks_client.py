"""
AKS Client Module

This module provides a client for interacting with Azure Kubernetes Service (AKS),
focusing specifically on node pool operations (create, scale, delete).
It handles authentication with Azure services using Managed Identity
or other authentication methods provided by DefaultAzureCredential.

The client also validates node readiness after operations using Kubernetes API.
"""

import os
import time
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Any

# Third party imports
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.core.pipeline.policies import RetryPolicy, RetryMode
from azure.core.pipeline.transport import RequestsTransport

# Local imports
from utils.logger_config import get_logger, setup_logging
from .kubernetes_client import KubernetesClient

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


class AKSClient:
    """
    Client for Azure Kubernetes Service (AKS) operations.

    This client handles authentication with Azure services and provides
    methods for managing AKS node pools (create, scale, delete).
    It also validates node readiness using Kubernetes API.
    """

    def __init__(
        self,
        subscription_id: Optional[str] = None,
        resource_group: Optional[str] = None,
        cluster_name: Optional[str] = None,
        use_managed_identity: bool = False,
        kube_config_file: Optional[str] = os.path.expanduser("~/.kube/config"),
        kubernetes_client: Optional[KubernetesClient] = None,  # pylint: disable=unused-argument
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
            kubernetes_client: Optional pre-configured KubernetesClient instance.
                              If not provided, one will be created using kube_config_file.
        """
        # Get subscription ID from environment if not provided
        self.subscription_id = subscription_id or os.getenv("AZURE_MI_SUBSCRIPTION_ID")
        if not self.subscription_id:
            raise ValueError(
                "Subscription ID is required. Provide it directly or set AZURE_MI_SUBSCRIPTION_ID environment variable."
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
        self.result_dir = result_dir

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
        node_count: int = 1,
        cluster_name: Optional[str] = None,
        node_pool_label: Optional[str] = None,
        gpu_node_pool: bool = False,
    ) -> Any:
        """
        Create a new node pool in the AKS cluster.

        Args:
            node_pool_name: The name for the new node pool
            vm_size: The VM size for the nodes (e.g., 'Standard_DS2_v2')
            node_count: The number of nodes to create (default: 1)
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            node_pool_label: Label selector to identify nodes in this node pool (default: None)
                            If None, will use agentpool={node_pool_name}

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

        # Build parameters for node pool creation
        parameters = {
            "count": node_count,
            "vm_size": vm_size,
            "os_type": "Linux",
            "mode": "User",
        }

        self.vm_size = vm_size

        start_time = time.time()

        try:
            logger.info(
                f"Creating node pool {node_pool_name} in cluster {cluster_name}"
            )
            self.aks_client.agent_pools.begin_create_or_update(
                resource_group_name=self.resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
                parameters=parameters,
            ).result()

            # Use agentpool=node_pool_name as default label if not specified
            label_selector = node_pool_label or f"agentpool={node_pool_name}"

            try:
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=operation_timeout_minutes,
                    label_selector=label_selector,
                )
                logger.info(
                    f"All {node_count} nodes in pool {node_pool_name} are ready"
                )

                end_time = time.time()
                duration = end_time - start_time
                # Verify NVIDIA drivers if this is a GPU node pool
                pod_logs = None
                if gpu_node_pool and node_count > 0:
                    logger.info(
                        f"Verifying NVIDIA drivers for GPU node pool '{node_pool_name}'"
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                self._record_metrics(
                    "create_node_pool",
                    node_pool_name,
                    duration,
                    True,
                    node_count,
                    logs=pod_logs,
                )
            except Exception as k8s_err:
                error_msg = str(k8s_err)
                logger.error(f"Error waiting for node readiness: {error_msg}")

                end_time = time.time()
                duration = end_time - start_time
                self._record_metrics(
                    "create_node_pool",
                    node_pool_name,
                    duration,
                    False,
                    node_count,
                    error_msg,
                )
                raise

            return True

        except Exception as e:
            error_msg = str(e)
            end_time = time.time()
            duration = end_time - start_time
            self._record_metrics(
                "create_node_pool",
                node_pool_name,
                duration,
                False,
                node_count,
                error_msg,
            )

            logger.error(f"Error creating node pool {node_pool_name}: {error_msg}")
            raise

    def scale_node_pool(
        self,
        node_pool_name: str,
        node_count: int,
        cluster_name: Optional[str] = None,
        node_pool_label: Optional[str] = None,
        operation_type: str = "scale",
        gpu_node_pool: bool = False,
    ) -> Any:
        """
        Scale a node pool to the specified node count.

        Args:
            node_pool_name: The name of the node pool
            node_count: The desired number of nodes
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            node_pool_label: Label selector to identify nodes in this node pool (default: None)
                            If None, will use agentpool={node_pool_name}
            operation_type: Type of scaling operation for metrics (default: "scale")
                          Can be "scale_up" or "scale_down" for more specific metrics

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

        start_time = time.time()

        try:
            # Get current node pool configuration
            node_pool = self.get_node_pool(node_pool_name, cluster_name)

            current_count = node_pool.count
            if operation_type == "scale" and current_count is not None:
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

            # Store VM size for metrics
            self.vm_size = node_pool.vm_size

            # Update the node count
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
            label_selector = node_pool_label or f"agentpool={node_pool_name}"

            try:
                ready_nodes = self.k8s_client.wait_for_nodes_ready(
                    node_count=node_count,
                    operation_timeout_in_minutes=self.operation_timeout_minutes,
                    label_selector=label_selector,
                )
                logger.info(
                    f"All {node_count} nodes in pool {node_pool_name} are ready"
                )

                end_time = time.time()
                duration = end_time - start_time
                pod_logs = None
                # Verify NVIDIA drivers if this is a GPU node pool and we're scaling up
                if gpu_node_pool and node_count > 0:
                    logger.info(
                        f"Verifying NVIDIA drivers for GPU node pool '{node_pool_name}' after scaling"
                    )
                    pod_logs = self.k8s_client.verify_nvidia_smi_on_node(ready_nodes)
                self._record_metrics(
                    operation_type,
                    node_pool_name,
                    duration,
                    True,
                    node_count,
                    logs=pod_logs,
                )
            except Exception as k8s_err:
                error_msg = str(k8s_err)
                logger.error(f"Error waiting for node readiness: {error_msg}")

                end_time = time.time()
                duration = end_time - start_time
                self._record_metrics(
                    operation_type,
                    node_pool_name,
                    duration,
                    False,
                    node_count,
                    error_msg,
                )
                raise

            return True

        except Exception as e:
            error_msg = str(e)
            end_time = time.time()
            duration = end_time - start_time
            self._record_metrics(
                operation_type, node_pool_name, duration, False, node_count, error_msg
            )

            logger.error(f"Error scaling node pool {node_pool_name}: {error_msg}")
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

        # Try to get node pool info before deletion for metrics
        try:
            node_pool = self.get_node_pool(node_pool_name, cluster_name)
            self.vm_size = node_pool.vm_size
        except Exception as e:
            logger.warning(f"Could not get node pool info before deletion: {str(e)}")
            self.vm_size = "unknown"

        start_time = time.time()

        try:
            logger.info(
                f"Deleting node pool {node_pool_name} from cluster {cluster_name}"
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

            end_time = time.time()
            duration = end_time - start_time
            self._record_metrics("delete_node_pool", node_pool_name, duration, True)

            return True

        except Exception as e:
            error_msg = str(e)
            end_time = time.time()
            duration = end_time - start_time
            self._record_metrics(
                "delete_node_pool", node_pool_name, duration, False, None, error_msg
            )

            logger.error(f"Error deleting node pool {node_pool_name}: {error_msg}")
            raise

    def _record_metrics(
        self,
        operation: str,
        node_pool_name: str,
        duration: float,
        success: bool,
        node_count: Optional[int] = None,
        error_msg: Optional[str] = None,
        logs: Optional[str] = None,
    ) -> None:
        """
        Record metrics for an operation.

        Args:
            operation: The name of the operation (create_node_pool, scale_up, scale_down, delete_node_pool)
            node_pool_name: The name of the node pool
            duration: The duration of the operation in seconds
            success: Whether the operation was successful
            node_count: The node count for scaling operations
            error_msg: Error message if operation failed
            logs: Additional logs from the operation
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_op_name = (
                operation.replace(" ", "_")
                .replace("/", "_")
                .replace("\\", "_")
                .replace(":", "_")
            )
            filename = f"azure_{clean_op_name}_{timestamp}.json"
            metrics = {}

            operation_info = {
                "operation": operation,
                "duration_seconds": duration,
                "start_time": datetime.fromtimestamp(
                    time.time() - duration
                ).isoformat(),
                "end_time": datetime.fromtimestamp(time.time()).isoformat(),
                "success": success,
                "node_pool_name": node_pool_name,
                "error": error_msg,
                "logs": logs,
            }

            # Add VM size if available
            if hasattr(self, "vm_size") and self.vm_size:
                operation_info["vm_size"] = self.vm_size

            if node_count is not None:
                operation_info["node_count"] = node_count

            # Add cluster data
            try:
                cluster_data = self.get_cluster_data()
                metrics["cluster_data"] = cluster_data
            except Exception as cluster_err:
                logger.warning(
                    f"Failed to get cluster data for metrics: {str(cluster_err)}"
                )
                metrics["cluster_data"] = None

            # Add operation info
            metrics["operation_info"] = operation_info

            result_file = (
                os.path.join(self.result_dir, filename) if self.result_dir else filename
            )
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            logger.info(f"Metrics saved to {result_file}")
        except Exception as e:
            logger.warning(f"Failed to record metrics: {str(e)}")
