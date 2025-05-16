# Node Pool Operations

This module provides functionality for AKS node pool operations including:
- Create node pool
- Scale up node pool
- Scale down node pool
- Delete node pool

## Usage

### Basic Operations

```bash
python node_pool_operations.py \
  --subscription-id YOUR_SUBSCRIPTION_ID \
  --resource-group YOUR_RESOURCE_GROUP \
  --cluster-name YOUR_AKS_CLUSTER_NAME \
  --node-pool-name nptest \
  --vm-size Standard_DS2_v2 \
  --initial-count 1 \
  --scale-up-count 3 \
  --scale-down-count 1
```

### Adding Latency Measurements

To add latency measurements to operations, you can use the provided `latency_decorators.py` module:

1. Import the decorator:
```python
from latency_decorators import measure_latency
```

2. Apply the decorator to methods in the NodePoolOperations class:
```python
# Basic usage - will create operation name from function name and arguments
@measure_latency()
def create_node_pool(self, node_pool_name, vm_size="Standard_DS2_v2", node_count=1):
    # Implementation...

# Using custom operation name with formatting
@measure_latency("Scale node pool '{node_pool_name}' to {node_count} nodes")
def scale_node_pool(self, node_pool_name, node_count):
    # Implementation...

# Using fixed operation name
@measure_latency("Delete node pool operation")
def delete_node_pool(self, node_pool_name):
    # Implementation...
```

3. Add logic to collect and report metrics as needed.

## Parameters

- `--subscription-id`: Azure subscription ID
- `--resource-group`: Resource group name 
- `--cluster-name`: AKS cluster name
- `--node-pool-name`: Name for the node pool (default: nptest)
- `--vm-size`: VM size for the nodes (default: Standard_DS2_v2)
- `--initial-count`: Initial node count (default: 1)
- `--scale-up-count`: Number of nodes to scale up to (default: 3)
- `--scale-down-count`: Number of nodes to scale down to (default: 1)

## Requirements

- azure-mgmt-containerservice
- azure-identity

## Integration with Telescope

This module can be used to test and benchmark AKS node pool operations as part of the Telescope performance testing framework.
