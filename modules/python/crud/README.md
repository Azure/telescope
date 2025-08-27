# Overview

The CRUD module provides comprehensive node pool management operations for Kubernetes clusters across multiple cloud providers (Azure, AWS). It supports creating, scaling, deleting node pools, and collecting benchmark results from CRUD operations.

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

### Common Variables
```bash
pushd modules/python
PYTHON_SCRIPT_FILE=crud/main.py
CREATE_NODE_COUNT=0
SCALE_NODE_COUNT=2
SCALE_STEP_SIZE=1
STEP_TIME_OUT=600
RESULT_DIR=/tmp/${RUN_ID}
GPU_NODE_POOL=True
STEP_WAIT_TIME=30
export RUN_ID=$RUN_ID
export SCENARIO_TYPE=$SCENARIO_TYPE
export SCENARIO_NAME=$SCENARIO_NAME
```
### Azure Variables
```bash
NODE_POOL_NAME=h100nodepool
VM_SIZE=Standard_NC40ads_H100_v5
CLOUD="azure"
export REGION="australiaeast"
export AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```
### AWS Variables
```bash
NODE_POOL_NAME=a100nodepool
VM_SIZE=p4d.24xlarge
export AWS_DEFAULT_REGION="us-east-1"
CAPACITY_TYPE="CAPACITY_BLOCK"
```
mkdir -p $RESULT_DIR
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
    --step-timeout $STEP_TIME_OUT \
    ${GPU_NODE_POOL:+--gpu-node-pool}
    --capacity-type "${CAPACITY_TYPE:-ON_DEMAND}"
```

## Scale Up Node Pool
```bash

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE scale \
    --cloud $CLOUD \
    --run-id $RUN_ID \
    --result-dir $RESULT_DIR \
    --node-pool-name $NODE_POOL_NAME \
    --target-count $SCALE_NODE_COUNT \
    --scale-step-size $SCALE_STEP_SIZE \
    --step-wait-time $STEP_WAIT_TIME \
    --step-timeout $STEP_TIME_OUT \
    ${GPU_NODE_POOL:+--gpu-node-pool}
```

## Scale Down Node Pool
```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE scale \
    --cloud $CLOUD \
    --run-id $RUN_ID \
    --result-dir $RESULT_DIR \
    --node-pool-name $NODE_POOL_NAME \
    --target-count $CREATE_NODE_COUNT \
    --scale-step-size $SCALE_STEP_SIZE \
    --step-wait-time $STEP_WAIT_TIME \
    --step-timeout $STEP_TIME_OUT \
    ${GPU_NODE_POOL:+--gpu-node-pool}
```

## Delete Node Pool

Delete an existing node pool:

```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE delete \
    --cloud $CLOUD \
    --run-id $RUN_ID \
    --result-dir $RESULT_DIR \
    --node-pool-name $NODE_POOL_NAME \
    --step-timeout $STEP_TIME_OUT
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
    --step-timeout $STEP_TIME_OUT \
    ${GPU_NODE_POOL:+--gpu-node-pool}
```

## Collect Benchmark Results

Collect and process benchmark results from JSON files:

```bash
# Set environment variables for collection
export RESULT_DIR=/tmp/${RUN_ID}
export RUN_URL="https://example.com/pipeline/run"

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect
```