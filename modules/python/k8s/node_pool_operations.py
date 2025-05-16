import argparse
import time
import os
import logging
import sys

# Add the parent directory to the path to import utils correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.core.exceptions import HttpResponseError
from utils.logger_config import get_logger, setup_logging
from latency_decorators import measure_latency
# Configure logging
setup_logging()
logger = get_logger(__name__)
# Suppress noisy Azure SDK logs - set to ERROR to completely hide INFO and WARNING messages
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
logging.getLogger("azure.identity").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline").setLevel(logging.ERROR)
logging.getLogger("msal").setLevel(logging.ERROR)
# Initialize operation metrics storage
if not hasattr(sys.modules[__name__], "_operation_metrics"):
    setattr(sys.modules[__name__], "_operation_metrics", [])
class NodePoolOperations:
    """Performs AKS node pool operations"""
    
    def __init__(self, resource_group):
        """Initialize with Azure resource identifiers"""
        managed_identity_client_id = os.getenv("AZURE_MI_ID")
        self.subscription_id = os.getenv("AZURE_MI_SUBSCRIPTION_ID")
        self.resource_group = resource_group
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

    @measure_latency(operation_name="create_node_pool", cloud_provider="azure")
    def create_node_pool(self, node_pool_name, vm_size, node_count=1):
        """Create a new node pool"""
        logger.info(f"Creating node pool '{node_pool_name}'")
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
    
    @measure_latency(operation_name="scale_node_pool", cloud_provider="azure")
    def scale_node_pool(self, node_pool_name, node_count):
        """Scale a node pool to specified count"""
        logger.info(f"Scaling node pool '{node_pool_name}' to {node_count} nodes")
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
    
    @measure_latency(operation_name="delete_node_pool", cloud_provider="azure")
    def delete_node_pool(self, node_pool_name):
        """Delete a node pool"""
        logger.info(f"Deleting node pool '{node_pool_name}'")
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
    
    def run_all_operations(self, node_pool_name, vm_size, 
                         initial_count, scale_up_count, scale_down_count):
        """Run all node pool operations in sequence"""
        # Create node pool
        create_success = self.create_node_pool(
            node_pool_name=node_pool_name, 
            vm_size=vm_size,
            node_count=initial_count
        )
        
        if create_success:
            # Give some time for the node pool to stabilize
            logger.info(f"Waiting 30s for node pool to stabilize...")
            time.sleep(30)
            
            # Scale up
            scale_up_success = self.scale_node_pool(
                node_pool_name=node_pool_name, 
                node_count=scale_up_count
            )
            
            if scale_up_success:
                # Give some time for scaling up to complete
                logger.info(f"Waiting 30s for scale up to complete...")
                time.sleep(30)
                
                # Scale down
                scale_down_success = self.scale_node_pool(
                    node_pool_name=node_pool_name, 
                    node_count=scale_down_count
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
        delete_success = self.delete_node_pool(node_pool_name=node_pool_name)
        
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
        """Return any metrics collected by the decorators"""
        import sys
        module = sys.modules[__name__]
        if hasattr(module, "_operation_metrics"):
            return getattr(module, "_operation_metrics")
        return []            

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Perform AKS node pool operations')
    # Add operation name argument cloud provider
    parser.add_argument('--cloud-provider', default='azure',help='Cloud provider (azure)')
    parser.add_argument('--operation-name', required=True, help='Operation name to perform (create, scale_up, scale_down, delete, all)')
    parser.add_argument('--run-id', required=True, help='Resource group name')
    parser.add_argument('--node-pool-name', required=True, help='Node pool name')
    parser.add_argument('--vm-size', default='Standard_DS2_v2', help='VM size for node pool')
    parser.add_argument('--initial-count', type=int, default=0, help='Initial node count')
    parser.add_argument('--scale-up-count', type=int, default=0, help='Scale up node count')
    parser.add_argument('--scale-down-count', type=int, default=0, help='Scale down node count')
    parser.add_argument('--output-file', help='Output file to save metrics (optional, defaults to metrics_<operation>_<timestamp>.json)')
    
    args = parser.parse_args()
    
    node_pool_ops = NodePoolOperations(
        resource_group=args.run_id,
    )
    node_pool_ops.cluster_name = node_pool_ops.get_cluster_name()
    
    # Run the specified operation
    if args.operation_name == "create":
        success = node_pool_ops.create_node_pool(
            node_pool_name=args.node_pool_name,
            vm_size=args.vm_size,
            node_count=args.initial_count
        )
    elif args.operation_name == "scale_up":
        success = node_pool_ops.scale_node_pool(
            node_pool_name=args.node_pool_name,
            node_count=args.scale_up_count
        )
    elif args.operation_name == "scale_down":
        success = node_pool_ops.scale_node_pool(
            node_pool_name=args.node_pool_name,
            node_count=args.scale_down_count
        )
    elif args.operation_name == "delete":
        success = node_pool_ops.delete_node_pool(node_pool_name=args.node_pool_name)
    elif args.operation_name == "all":
        success = node_pool_ops.run_all_operations(
            node_pool_name=args.node_pool_name,
            vm_size=args.vm_size,
            initial_count=args.initial_count,
            scale_up_count=args.scale_up_count,
            scale_down_count=args.scale_down_count
        )
    else:
        logger.error(f"Unknown operation name: {args.operation_name}")
        return False

    # Get collected metrics and print/save them
    metrics = node_pool_ops.get_collected_metrics()
    logger.info(f"Collected {len(metrics)} operation metrics")
    
    # Generate default output filename if not provided
    if metrics:
        if not args.output_file:
            # Generate a timestamp and create a default filename
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"metrics_{args.operation_name}_{timestamp}.json"
        else:
            output_file = args.output_file
            
        # Create directory if it doesn't exist
        import os
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        
        # Save metrics to file
        import json
        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        logger.info(f"Metrics saved to {output_file}")
    else:
        logger.warning("No metrics collected to save")
    
    # Print metrics summary
    for metric in metrics:
        op = metric["operation"]
        dur = metric["duration_seconds"]
        status = "SUCCESS" if metric["success"] else "FAILED"
        logger.info(f"[METRIC] {op}: {dur:.2f}s ({status})")
if __name__ == "__main__":
    main()
