# Overview

The CRUD module provides comprehensive node pool management operations for Kubernetes clusters across multiple cloud providers (Azure, AWS, GCP). It supports creating, scaling, deleting node pools, and collecting benchmark results from CRUD operations.

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

## Supported Operations

- **create**: Create a new node pool
- **scale**: Scale an existing node pool up or down
- **delete**: Delete an existing node pool  
- **all**: Run complete lifecycle (create → scale up → scale down → delete)
- **collect**: Collect and process benchmark results

## Define Variables

```bash
pushd modules/python
PYTHON_SCRIPT_FILE=crud/main.py
VM_SIZE=Standard_NC40ads_H100_v5
CREATE_NODE_COUNT=0
SCALE_NODE_COUNT=2
SCALE_STEP_SIZE=1
NODE_POOL_NAME=h100nodepool
CLOUD="azure"  # "aws"
STEP_TIME_OUT=600
RESULT_DIR=/tmp/${RUN_ID}
GPU_NODE_POOL=True
STEP_WAIT_TIME=30
REGION="australiaeast"  # or your cloud region

mkdir -p $RESULT_DIR

# export AWS_DEFAULT_REGION=us-east-1 # Uncomment and set for AWS
export RUN_ID=$RUN_ID
export SCENARIO_TYPE=$SCENARIO_TYPE
export SCENARIO_NAME=$SCENARIO_NAME
export REGION="eastus"  # for azure
export AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

## Create Node Pool

Create a new node pool in your Kubernetes cluster:
```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE create \
  --cloud $CLOUD \
  --run-id $RUN_ID \
  --result-dir "$RESULT_DIR" \
  --node-pool-name "$NODE_POOL_NAME" \
  --vm-size $VM_SIZE \
  --node-count $CREATE_NODE_COUNT \
  --step-timeout 600 \
  --gpu-node-pool  # Include this flag for GPU node pools
```

## Scale Up Node Pool

Scale an existing node pool to a target count:

```bash

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE scale \
  --cloud $CLOUD \
  --run-id $RUN_ID \
  --result-dir $RESULT_DIR \
  --node-pool-name $NODE_POOL_NAME \
  --target-count $SCALE_NODE_COUNT \
  --scale-step-size $SCALE_STEP_SIZE \
  --step-wait-time $STEP_WAIT_TIME \
  --step-timeout 600
```

## Scale Down Node Pool

Scale an existing node pool to a target count:

```bash

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE scale \
  --cloud $CLOUD \
  --run-id $RUN_ID \
  --result-dir $RESULT_DIR \
  --node-pool-name $NODE_POOL_NAME \
  --target-count $CREATE_NODE_COUNT \
  --scale-step-size $SCALE_STEP_SIZE \
  --step-wait-time $STEP_WAIT_TIME \
  --step-timeout 600
```

## Delete Node Pool

Delete an existing node pool:

```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE delete \
  --cloud $CLOUD \
  --run-id $RUN_ID \
  --result-dir $RESULT_DIR \
  --node-pool-name $NODE_POOL_NAME \
  --step-timeout 600
```

## Complete Lifecycle (All Operations)

Run the complete node pool lifecycle - create, scale up, scale down, and delete:

```bash

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE all \
  --cloud $CLOUD \
  --run-id $RUN_ID \
  --result-dir $RESULT_DIR \
  --node-pool-name $NODE_POOL_NAME \
  --vm-size $VM_SIZE \
  --node-count $CREATE_NODE_COUNT \
  --target-count $SCALE_NODE_COUNT \
  --scale-step-size $SCALE_STEP_SIZE \
  --step-wait-time $STEP_WAIT_TIME \
  --step-timeout 600
```

## Collect Benchmark Results

Collect and process benchmark results from JSON files:

```bash
# Set environment variables for collection
export RESULT_DIR=/tmp/${RUN_ID}
export RUN_URL="https://example.com/pipeline/run"


PYTHONPATH=$PYTHONPATH:$(pwd) python3 crud/main.py collect
```

## AWS-Specific Options

For AWS deployments, you can specify capacity type:

```bash
CAPACITY_TYPE="SPOT"  # or "ON_DEMAND", "CAPACITY_BLOCK"

PYTHONPATH=$PYTHONPATH:$(pwd) python3 crud/main.py create \
  --cloud aws \
  --run-id $RUN_ID \
  --result-dir $RESULT_DIR \
  --node-pool-name $NODE_POOL_NAME \
  --vm-size "t3.medium" \
  --node-count $NODE_COUNT \
  --capacity-type $CAPACITY_TYPE \
  --step-timeout 600
```

## Common Arguments

All node pool operations support these common arguments:

- `--cloud`: Cloud provider (`azure`, `aws`, `gcp`)
- `--run-id`: Unique run identifier (required)
- `--result-dir`: Directory to save results (default: current directory)
- `--kube-config`: Path to kubeconfig file (optional)
- `--step-timeout`: Timeout for each operation in seconds (default: 600)
- `--gpu-node-pool`: Flag for GPU-enabled node pools
- `--capacity-type`: AWS/Azure capacity type (`ON_DEMAND`, `SPOT`, `CAPACITY_BLOCK`)

## Progressive Scaling

The scale and all operations support progressive scaling, where nodes are added/removed in steps:

- `--scale-step-size`: Number of nodes to add/remove per step (default: 1)
- `--step-wait-time`: Wait time between scaling steps in seconds (default: 30)

Progressive scaling is automatically enabled when `scale-step-size` is different from the target count.

## GPU Support

When using `--gpu-node-pool`, the module automatically:
1. Installs the GPU device plugin
2. Verifies the plugin installation
3. Configures the node pool for GPU workloads

Example VM sizes for GPU workloads:
- **Azure**: `Standard_NC6s_v3`, `Standard_ND40rs_v2`
- **AWS**: `p3.2xlarge`, `g4dn.xlarge`
