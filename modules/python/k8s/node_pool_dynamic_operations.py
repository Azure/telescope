#!/usr/bin/env python3
"""
This script performs AKS node pool operations with dynamic operation names:
- Create node pool
- Scale up node pool
- Scale down node pool
- Delete node pool

This version dynamically applies the operation name from command-line arguments
"""

import argparse
import time
import os
import logging
import sys
import json
from datetime import datetime

# Add the parent directory to the path to import utils correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.core.exceptions import HttpResponseError

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress noisy Azure SDK logs
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
logging.getLogger("azure.identity").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline").setLevel(logging.ERROR)
logging.getLogger("msal").setLevel(logging.ERROR)

class NodePoolOperations:
    """Performs AKS node pool operations with dynamic operation names"""
    
    def __init__(self, resource_group, cloud_provider="azure", **kwargs):
        """Initialize with Azure resource identifiers"""
        self.cloud_provider = cloud_provider
        managed_identity_client_id = os.getenv("AZURE_MI_ID")
        self.subscription_id = os.getenv("AZURE_MI_SUBSCRIPTION_ID")
        self.resource_group = resource_group
        self.vm_size = kwargs.get("vm_size", None)
        self.initial_count = kwargs.get("initial_count", None)
        self.desired_count = kwargs.get("desired_count", None)
        if managed_identity_client_id:
            self.credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
        else:
            self.credential = ManagedIdentityCredential()
        self.aks_client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self.subscription_id
        )

        if not self.aks_client:
            error_msg = "Failed to initialize AKS client."
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    def measure_operation(self, operation_name, func, *args, **kwargs):
        """Measure operation latency and save metrics"""
        logger.info(f"Starting operation: {operation_name}")
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            duration = end_time - start_time
            
            success_status = "SUCCESS" if result else "FAILED"
            logger.info(f"Operation {operation_name} completed with status {success_status} in {duration:.2f} seconds")
            
            # Store metrics
            metrics = {
                "cloud_provider": self.cloud_provider,
                "operation": operation_name,
                "duration_seconds": duration,
                "start_time": datetime.fromtimestamp(start_time).isoformat(),
                "end_time": datetime.fromtimestamp(end_time).isoformat(),
                "success": bool(result),
                "vm_size": self.vm_size if hasattr(self, 'vm_size') else None,
                "initial_count": self.initial_count if hasattr(self, 'initial_count') else None,
                "desired_count": self.desired_count if hasattr(self, 'desired_count') else None
            }
            
            # Save metrics to file
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                clean_op_name = operation_name.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
                filename = f"{self.cloud_provider}_{clean_op_name}_{timestamp}.json"
                
                with open(filename, 'w') as f:
                    json.dump(metrics, f, indent=2)
                logger.info(f"Metrics automatically saved to {filename}")
            except Exception as save_error:
                logger.warning(f"Failed to automatically save metrics to file: {save_error}")
                        
            return result
        
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"Operation {operation_name} failed after {duration:.2f} seconds: {str(e)}")
            raise
    
    def create_node_pool(self, node_pool_name, vm_size, node_count=1):
        """Create a new node pool"""
            
        logger.info(f"Creating node pool '{node_pool_name}'")
        
        def _create_node_pool():
            try:
                result = self.aks_client.agent_pools.begin_create_or_update(
                    resource_group_name=self.resource_group,
                    resource_name=self.cluster_name,
                    agent_pool_name=node_pool_name,
                    parameters={
                        "count": node_count,
                        "vm_size": vm_size,
                        "mode": "User",
                        "os_type": "Linux"
                    }
                ).result()
                logger.info(f"Node pool '{node_pool_name}' created successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to create node pool '{node_pool_name}': {str(e)}")
                return False
        
        return self.measure_operation("create_node_pool", _create_node_pool)
    
    def scale_node_pool(self, node_pool_name, node_count, operation_name=None):
        """Scale a node pool to specified count"""
        logger.info(f"Scaling node pool '{node_pool_name}' to {node_count} nodes")
        
        def _scale_node_pool():
            try:
                # First get the current node pool config
                node_pool = self.aks_client.agent_pools.get(
                    resource_group_name=self.resource_group,
                    resource_name=self.cluster_name,
                    agent_pool_name=node_pool_name
                )
                
                # Update only the node count
                node_pool.count = node_count
                
                result = self.aks_client.agent_pools.begin_create_or_update(
                    resource_group_name=self.resource_group,
                    resource_name=self.cluster_name,
                    agent_pool_name=node_pool_name,
                    parameters=node_pool
                ).result()
                logger.info(f"Node pool '{node_pool_name}' scaled to {node_count} nodes successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to scale node pool '{node_pool_name}': {str(e)}")
                return False
        
        return self.measure_operation(operation_name, _scale_node_pool)
    
    def delete_node_pool(self, node_pool_name):
        """Delete a node pool"""
        if operation_name is None:
            operation_name = f"delete_node_pool_{node_pool_name}"
            
        logger.info(f"Deleting node pool '{node_pool_name}'")
        
        def _delete_node_pool():
            try:
                self.aks_client.agent_pools.begin_delete(
                    resource_group_name=self.resource_group,
                    resource_name=self.cluster_name,
                    agent_pool_name=node_pool_name
                ).result()
                logger.info(f"Node pool '{node_pool_name}' deleted successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to delete node pool '{node_pool_name}': {str(e)}")
                return False
        
        return self.measure_operation("delete_node_pool", _delete_node_pool)
    
    def run_all_operations(self, node_pool_name, vm_size, 
                           initial_count, scale_up_count, scale_down_count,
                           operation_name_prefix=None):
        """Run all node pool operations in sequence"""
        prefix = operation_name_prefix or ""
        
        # Create node pool
        create_success = self.create_node_pool(
            node_pool_name=node_pool_name, 
            vm_size=vm_size,
            node_count=initial_count,
            operation_name=f"{prefix}create_node_pool" if prefix else None
        )
        
        if create_success:
            # Give some time for the node pool to stabilize
            logger.info(f"Waiting 30s for node pool to stabilize...")
            time.sleep(30)
            
            # Scale up
            scale_up_success = self.scale_node_pool(
                node_pool_name=node_pool_name, 
                node_count=scale_up_count,
                operation_name=f"{prefix}scale_up_node_pool" if prefix else None
            )
            
            if scale_up_success:
                # Give some time for scaling up to complete
                logger.info(f"Waiting 30s for scale up to complete...")
                time.sleep(30)
                
                # Scale down
                scale_down_success = self.scale_node_pool(
                    node_pool_name=node_pool_name, 
                    node_count=scale_down_count,
                    operation_name=f"{prefix}scale_down_node_pool" if prefix else None
                )
                
                # Give some time for scaling down to complete
                logger.info(f"Waiting 30s for scale down to complete...")
                time.sleep(30)
            else:
                scale_down_success = False
        else:
            scale_up_success = False
            scale_down_success = False
        
        # Delete node pool
        delete_success = self.delete_node_pool(
            node_pool_name=node_pool_name,
            operation_name=f"{prefix}delete_node_pool" if prefix else None
        )
        
        return create_success and scale_up_success and scale_down_success and delete_success

    def get_cluster_name(self):
        """Get the AKS cluster name"""
        try:
            # List clusters in the given resource group
            clusters = list(self.aks_client.managed_clusters.list_by_resource_group(self.resource_group))

            if clusters:
                return clusters[0].name
            logger.error("No AKS clusters found in resource group: %s", self.resource_group)
            raise ValueError("No AKS clusters found in resource group")

        except Exception as e:
            logger.error("Error getting AKS cluster name: %s", str(e))
            raise e

    def get_collected_metrics(self):
        """Return all collected metrics"""
        return OPERATION_METRICS

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Perform AKS node pool operations')
    subparsers = parser.add_subparsers(dest='command')

    # Sub-Command for Create Node Pool
    create_parser = subparsers.add_parser('create', help='Create a new node pool')
    create_parser.add_argument('--run-id', required=True, help='Resource group name')
    create_parser.add_argument('--node-pool-name', required=True, help='Node pool name')
    create_parser.add_argument('--vm-size', default='Standard_DS2_v2', help='VM size for node pool')
    create_parser.add_argument('--node-count', type=int, default=1, help='Initial node count')
    create_parser.add_argument("--result-file", type=str, help="Path to the result file")

    # Sub-Command for Scale Node Pool
    scale_parser = subparsers.add_parser('scale', help='Scale a node pool')
    scale_parser.add_argument('--run-id', required=True, help='Resource group name')
    scale_parser.add_argument('--node-pool-name', required=True, help='Node pool name')
    scale_parser.add_argument('--node-count', type=int, required=True, help='Desired node count')
    scale_parser.add_argument("--result-file", type=str, help="Path to the result file")

    # Sub-Command for Delete Node Pool
    delete_parser = subparsers.add_parser('delete', help='Delete a node pool')
    delete_parser.add_argument('--run-id', required=True, help='Resource group name')
    delete_parser.add_argument('--node-pool-name', required=True, help='Node pool name')
    delete_parser.add_argument("--result-file", type=str, help="Path to the result file")


    # Common arguments for all commands
    for p in [create_parser, scale_parser, delete_parser]:
        p.add_argument('--run-id', required=True, help='Resource group name')
        p.add_argument('--node-pool-name', required=True, help='Node pool name') 
        p.add_argument('--cloud-provider', default='azure', help='Cloud provider name (default: azure)')
        p.add_argument("--result-file", type=str, help="Path to the result file")

    # Command-specific arguments
    create_parser.add_argument('--vm-size', default='Standard_DS2_v2', help='VM size for node pool')
    create_parser.add_argument('--node-count', type=int, default=1, help='Initial node count')
    
    scale_parser.add_argument('--node-count', type=int, required=True, help='Desired node count')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
        
    # Initialize operations with appropriate parameters based on command
    if args.command == 'create':
        node_pool_ops = NodePoolOperations(
            resource_group=args.run_id,
            cloud_provider=args.cloud_provider,
            vm_size=args.vm_size,
            initial_count=args.node_count,
            desired_count=None
        )
    elif args.command == 'scale':
        node_pool_ops = NodePoolOperations(
            resource_group=args.run_id,
            cloud_provider=args.cloud_provider,
            vm_size=None,
            initial_count=None,
            desired_count=args.node_count
        )
    elif args.command == 'delete':
        node_pool_ops = NodePoolOperations(
            resource_group=args.run_id,
            cloud_provider=args.cloud_provider,
            vm_size=None,
            initial_count=None,
            desired_count=None
        )
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1
   
if __name__ == "__main__":
    main()
