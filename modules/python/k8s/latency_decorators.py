#!/usr/bin/env python3
"""
Decorators for measuring latency of operations.
Can be used with node_pool_operations.py to add latency measurement.
"""

import time
import logging
import functools
import inspect
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

def measure_latency(operation_name=None, cloud_provider="azure"):
    """
    Decorator for measuring the latency of a function.
    Records start time, end time, and calculates duration.
    Also saves the metrics to a file for each operation.
    
    Args:
        operation_name: Optional custom name for the operation.
                       If not provided, will use function name and arguments.
        cloud_provider: Cloud provider name (default: azure)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get or construct operation name
            if operation_name is not None:
                # Use provided operation name, possibly formatting it with args
                op_name = operation_name
                # If the operation name contains placeholders, try to format it
                if '{' in op_name and '}' in op_name:
                    try:
                        # Create a context dict from args and kwargs
                        ctx = {}
                        # Add self attributes if available
                        if args and hasattr(args[0], '__dict__'):
                            ctx.update(args[0].__dict__)
                        # Add positional args by parameter name if we can get them
                        sig = inspect.signature(func)
                        param_names = list(sig.parameters.keys())
                        for i, arg in enumerate(args):
                            if i < len(param_names):
                                ctx[param_names[i]] = arg
                        # Add keyword args
                        ctx.update(kwargs)
                        # Format the operation name
                        op_name = op_name.format(**ctx)
                    except (KeyError, IndexError) as e:
                        logger.warning(f"Could not format operation name: {e}")
            else:
                # Use function name and node pool name if available
                op_name = func.__name__
                if len(args) > 1 and isinstance(args[1], str):  # Assuming first arg after self is node_pool_name
                    op_name = f"{op_name} - {args[1]}"
            
            logger.info(f"Starting operation: {op_name}")
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                duration = end_time - start_time
                
                # Log results
                success_status = "SUCCESS" if result else "FAILED"
                logger.info(f"Operation {op_name} completed with status {success_status} in {duration:.2f} seconds")
                
                # Store metrics with cloud provider info
                metrics = {
                    "cloud_provider": cloud_provider,
                    "operation": op_name,
                    "duration_seconds": duration,
                    "start_time": datetime.fromtimestamp(start_time).isoformat(),
                    "end_time": datetime.fromtimestamp(end_time).isoformat(),
                    "success": bool(result)
                }
                
                # Save metrics to a file automatically
                try:
                    import os
                    import json
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Clean the operation name for use in a filename
                    clean_op_name = op_name.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
                    # Generate filename with cloud provider, operation name and timestamp
                    filename = f"{cloud_provider}_{clean_op_name}_{timestamp}.json"
                    
                    # Create the file in the current directory
                    with open(filename, 'w') as f:
                        json.dump(metrics, f, indent=2)
                    logger.info(f"Metrics automatically saved to {filename}")
                except Exception as save_error:
                    logger.warning(f"Failed to automatically save metrics to file: {save_error}")
                
                # Also store metrics in module variable for backward compatibility
                module_name = func.__module__
                if not hasattr(sys.modules[module_name], "_operation_metrics"):
                    setattr(sys.modules[module_name], "_operation_metrics", [])
                
                sys.modules[module_name]._operation_metrics.append(metrics)
                
                # You can also export metrics to Prometheus here if needed
                # This would align with Azure best practices for monitoring and
                # integrate with the Telescope framework which uses Prometheus
                
                return result
            
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                logger.error(f"Operation {op_name} failed after {duration:.2f} seconds: {str(e)}")
                # Re-raise the exception to maintain original behavior
                raise
            
        return wrapper
    
    return decorator

# Example of how to use the decorator with NodePoolOperations:
"""
from latency_decorators import measure_latency

class NodePoolOperations:
    
    # Basic usage - will create operation name from function name and arguments
    @measure_latency(cloud_provider="azure")
    def create_node_pool(self, node_pool_name, vm_size="Standard_DS2_v2", node_count=1):
        # Implementation...
    
    # Using custom operation name with formatting and specifying cloud provider
    @measure_latency(operation_name="Scale node pool '{node_pool_name}' to {node_count} nodes", 
                    cloud_provider="azure")
    def scale_node_pool(self, node_pool_name, node_count):
        # Implementation...
    
    # Using fixed operation name with cloud provider
    @measure_latency(operation_name="Delete node pool operation", 
                    cloud_provider="gcp")  # Example with a different cloud provider
    def delete_node_pool(self, node_pool_name):
        # Implementation...

# Each operation will automatically save metrics to files with names like:
# - azure_create_node_pool_nptest_20250516_200245.json
# - azure_Scale_node_pool_nptest_to_3_nodes_20250516_200247.json
# - gcp_Delete_node_pool_operation_20250516_200249.json

# To access the metrics programmatically after running operations:
# import sys
# from your_module import NodePoolOperations
# metrics = getattr(sys.modules["your_module"], "_operation_metrics", [])
# for metric in metrics:
#     print(f"{metric['operation']} ({metric['cloud_provider']}) took {metric['duration_seconds']:.2f} seconds")
"""

