#!/usr/bin/env python3
"""
AKS Client Module

This module provides a client for interacting with Azure Kubernetes Service (AKS),
focusing specifically on node pool operations (create, scale, delete).
It handles authentication with Azure services using Managed Identity
or other authentication methods provided by DefaultAzureCredential.
"""

import os
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# Azure SDK imports
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Suppress noisy Azure SDK logs
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
logging.getLogger("azure.identity").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline").setLevel(logging.ERROR)
logging.getLogger("msal").setLevel(logging.ERROR)


class AKSClient:
    """
    Client for Azure Kubernetes Service (AKS) operations.
    
    This client handles authentication with Azure services and provides
    methods for managing AKS node pools (create, scale, delete).
    """
    
    def __init__(
        self, 
        subscription_id: Optional[str] = None, 
        resource_group: Optional[str] = None,
        cluster_name: Optional[str] = None,
        use_managed_identity: bool = True,
        managed_identity_client_id: Optional[str] = None
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
            managed_identity_client_id: The client ID for the managed identity.
                                       If not provided, will try to get it from 
                                       AZURE_MI_ID env var.
        """
        # Get subscription ID from environment if not provided
        self.subscription_id = subscription_id or os.getenv("AZURE_MI_SUBSCRIPTION_ID")
        if not self.subscription_id:
            raise ValueError("Subscription ID is required. Provide it directly or set AZURE_MI_SUBSCRIPTION_ID environment variable.")
            
        self.resource_group = resource_group
        self.cluster_name = cluster_name
        
        # Set up authentication
        if use_managed_identity:
            mi_client_id = managed_identity_client_id or os.getenv("AZURE_MI_ID")
            if mi_client_id:
                logger.info(f"Using Managed Identity with client ID for authentication")
                self.credential = ManagedIdentityCredential(client_id=mi_client_id)
            else:
                logger.info(f"Using default Managed Identity for authentication")
                self.credential = ManagedIdentityCredential()
        else:
            logger.info(f"Using DefaultAzureCredential for authentication")
            self.credential = DefaultAzureCredential()
            
        # Initialize AKS client
        self.aks_client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )
        
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
            clusters = list(self.aks_client.managed_clusters.list_by_resource_group(self.resource_group))
            
            if clusters:
                self.cluster_name = clusters[0].name
                logger.info(f"Found AKS cluster: {self.cluster_name}")
                return self.cluster_name
                
            logger.error(f"No AKS clusters found in resource group: {self.resource_group}")
            raise ValueError("No AKS clusters found in resource group")
            
        except HttpResponseError as e:
            logger.error(f"Error getting AKS clusters: {str(e)}")
            raise
    
    def get_node_pool(self, node_pool_name: str, cluster_name: Optional[str] = None) -> Any:
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
                agent_pool_name=node_pool_name
            )
            logger.info(f"Successfully retrieved node pool {node_pool_name}")
            return node_pool
        except ResourceNotFoundError:
            logger.error(f"Node pool {node_pool_name} not found in cluster {cluster_name}")
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
        os_type: str = "Linux", 
        mode: str = "User",
        wait: bool = True,
        record_time: bool = True
    ) -> Any:
        """
        Create a new node pool in the AKS cluster.
        
        Args:
            node_pool_name: The name for the new node pool
            vm_size: The VM size for the nodes (e.g., 'Standard_DS2_v2')
            node_count: The number of nodes to create (default: 1)
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            os_type: The OS type for the nodes (default: 'Linux')
            mode: The mode for the node pool (default: 'User')
            wait: Whether to wait for the operation to complete (default: True)
            record_time: Whether to record the operation time metrics (default: True)
            
        Returns:
            Node pool object if wait is True, otherwise the operation
            
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
            "os_type": os_type,
            "mode": mode,
        }
            
        start_time = time.time() if record_time else None
        
        try:
            logger.info(f"Creating node pool {node_pool_name} in cluster {cluster_name}")
            operation = self.aks_client.agent_pools.begin_create_or_update(
                resource_group_name=self.resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
                parameters=parameters
            )
            
            if wait:
                logger.info("Waiting for node pool creation to complete...")
                result = operation.result()
                logger.info(f"Node pool {node_pool_name} created successfully")
                
                if record_time:
                    end_time = time.time()
                    duration = end_time - start_time
                    self._record_metrics("create_node_pool", node_pool_name, duration, True)
                
                return result
            else:
                logger.info(f"Node pool {node_pool_name} creation initiated. Not waiting for completion.")
                return operation
                
        except Exception as e:
            if record_time:
                end_time = time.time()
                duration = end_time - start_time
                self._record_metrics("create_node_pool", node_pool_name, duration, False)
                
            logger.error(f"Error creating node pool {node_pool_name}: {str(e)}")
            raise
    
    def scale_node_pool(
        self,
        node_pool_name: str,
        node_count: int,
        cluster_name: Optional[str] = None,
        wait: bool = True,
        record_time: bool = True,
        operation_type: str = "scale"
    ) -> Any:
        """
        Scale a node pool to the specified node count.
        
        Args:
            node_pool_name: The name of the node pool
            node_count: The desired number of nodes
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            wait: Whether to wait for the operation to complete (default: True)
            record_time: Whether to record the operation time metrics (default: True)
            operation_type: Type of scaling operation for metrics (default: "scale")
                          Can be "scale_up" or "scale_down" for more specific metrics
            
        Returns:
            Node pool object if wait is True, otherwise the operation
            
        Raises:
            ValueError: If resource_group is not set or no cluster is found
            ResourceNotFoundError: If the cluster or node pool is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to scale node pool")
            
        cluster_name = cluster_name or self.get_cluster_name()
            
        start_time = time.time() if record_time else None
        
        try:
            # Get current node pool configuration
            node_pool = self.get_node_pool(node_pool_name, cluster_name)
            
            current_count = node_pool.count
            if operation_type == "scale" and current_count is not None:
                if node_count > current_count:
                    operation_type = "scale_up"
                elif node_count < current_count:
                    operation_type = "scale_down"
            
            # Check if auto-scaling is enabled
            if hasattr(node_pool, 'enable_auto_scaling') and node_pool.enable_auto_scaling:
                logger.warning(f"Node pool {node_pool_name} has auto-scaling enabled. Setting count may have no effect.")
                
            # Update the node count
            node_pool.count = node_count
            
            logger.info(f"Scaling node pool {node_pool_name} to {node_count} nodes")
            operation = self.aks_client.agent_pools.begin_create_or_update(
                resource_group_name=self.resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name,
                parameters=node_pool
            )
            
            if wait:
                logger.info("Waiting for node pool scaling to complete...")
                result = operation.result()
                logger.info(f"Node pool {node_pool_name} scaled to {node_count} nodes successfully")
                
                if record_time:
                    end_time = time.time()
                    duration = end_time - start_time
                    self._record_metrics(operation_type, node_pool_name, duration, True, node_count)
                
                return result
            else:
                logger.info(f"Node pool {node_pool_name} scaling initiated. Not waiting for completion.")
                return operation
                
        except Exception as e:
            if record_time:
                end_time = time.time()
                duration = end_time - start_time
                self._record_metrics(operation_type, node_pool_name, duration, False, node_count)
                
            logger.error(f"Error scaling node pool {node_pool_name}: {str(e)}")
            raise
    
    def delete_node_pool(
        self,
        node_pool_name: str,
        cluster_name: Optional[str] = None,
        wait: bool = True,
        record_time: bool = True
    ) -> bool:
        """
        Delete a node pool from the AKS cluster.
        
        Args:
            node_pool_name: The name of the node pool to delete
            cluster_name: The name of the AKS cluster. If not provided,
                         will use the one from initialization or try to find one.
            wait: Whether to wait for the operation to complete (default: True)
            record_time: Whether to record the operation time metrics (default: True)
            
        Returns:
            True if deletion was successful or initiated
            
        Raises:
            ValueError: If resource_group is not set or no cluster is found
            ResourceNotFoundError: If the cluster or node pool is not found
            HttpResponseError: If the Azure API request fails
        """
        if not self.resource_group:
            raise ValueError("Resource group is required to delete node pool")
            
        cluster_name = cluster_name or self.get_cluster_name()
        
        start_time = time.time() if record_time else None
            
        try:
            logger.info(f"Deleting node pool {node_pool_name} from cluster {cluster_name}")
            operation = self.aks_client.agent_pools.begin_delete(
                resource_group_name=self.resource_group,
                resource_name=cluster_name,
                agent_pool_name=node_pool_name
            )
            
            if wait:
                logger.info("Waiting for node pool deletion to complete...")
                operation.result()  # Wait for completion
                logger.info(f"Node pool {node_pool_name} deleted successfully")
                
                if record_time:
                    end_time = time.time()
                    duration = end_time - start_time
                    self._record_metrics("delete_node_pool", node_pool_name, duration, True)
            else:
                logger.info(f"Node pool {node_pool_name} deletion initiated. Not waiting for completion.")
                
            return True
                
        except Exception as e:
            if record_time and start_time:
                end_time = time.time()
                duration = end_time - start_time
                self._record_metrics("delete_node_pool", node_pool_name, duration, False)
                
            logger.error(f"Error deleting node pool {node_pool_name}: {str(e)}")
            raise
            
    def _record_metrics(self, operation: str, node_pool_name: str, duration: float, success: bool, node_count: Optional[int] = None) -> None:
        """
        Record metrics for an operation.
        
        Args:
            operation: The name of the operation (create_node_pool, scale_up, scale_down, delete_node_pool)
            node_pool_name: The name of the node pool
            duration: The duration of the operation in seconds
            success: Whether the operation was successful
            node_count: The node count for scaling operations
        """
        try:
            import json
            from datetime import datetime
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_op_name = operation.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
            filename = f"azure_{clean_op_name}_{timestamp}.json"
            
            metrics = {
                "cloud_provider": "azure",
                "operation": f"{operation}_{node_pool_name}",
                "duration_seconds": duration,
                "start_time": datetime.fromtimestamp(time.time() - duration).isoformat(),
                "end_time": datetime.fromtimestamp(time.time()).isoformat(),
                "success": success,
                "node_pool_name": node_pool_name
            }
            
            if node_count is not None:
                metrics["node_count"] = node_count
                
            # Create the file in the current directory
            with open(filename, 'w') as f:
                json.dump(metrics, f, indent=2)
            logger.info(f"Metrics saved to {filename}")
        except Exception as e:
            logger.warning(f"Failed to record metrics: {str(e)}")
    
    
# Example usage
if __name__ == "__main__":
    # This code is executed when the script is run directly
    import sys
    
    # Parse command line arguments
    if len(sys.argv) < 3:
        print("Usage: python aks_client.py <resource_group> <operation> [params...]")
        print("Operations: create, scale, delete")
        print("Examples:")
        print("  python aks_client.py my-resource-group create my-nodepool Standard_DS2_v2 3")
        print("  python aks_client.py my-resource-group scale my-nodepool 5")
        print("  python aks_client.py my-resource-group delete my-nodepool")
        sys.exit(1)
    
    resource_group = sys.argv[1]
    operation = sys.argv[2]
    
    # Create a client instance
    client = AKSClient(resource_group=resource_group) 
    
    try:
        # Get the cluster name
        cluster_name = client.get_cluster_name()
        print(f"Found AKS cluster: {cluster_name}")
        
        # Perform the requested operation
        if operation == "create" and len(sys.argv) >= 6:
            node_pool_name = sys.argv[3]
            vm_size = sys.argv[4]
            node_count = int(sys.argv[5])
            
            print(f"Creating node pool {node_pool_name} with {node_count} nodes...")
            result = client.create_node_pool(node_pool_name, vm_size, node_count)
            print(f"Node pool created successfully: {result.name}")
            
        elif operation == "scale" and len(sys.argv) >= 5:
            node_pool_name = sys.argv[3]
            node_count = int(sys.argv[4])
            
            print(f"Scaling node pool {node_pool_name} to {node_count} nodes...")
            result = client.scale_node_pool(node_pool_name, node_count)
            print(f"Node pool scaled successfully: {result.name}, new count: {result.count}")
            
        elif operation == "delete" and len(sys.argv) >= 4:
            node_pool_name = sys.argv[3]
            
            print(f"Deleting node pool {node_pool_name}...")
            client.delete_node_pool(node_pool_name)
            print("Node pool deleted successfully")
            
        else:
            print(f"Unknown operation or missing parameters: {operation}")
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
