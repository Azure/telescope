# Overview

## Configure

The example below installs 3 operatiors: network operator, gpu operator, and mpi operator. To install only specific operator(s), you can set the version for that specific operator only and leave the rest unset.

```bash
pushd modules/python
EFA_OPERATOR_VERSION="v0.5.7" # Set for AWS only
NETWORK_OPERATOR_VERSION="v25.7.0" # Set for Azure only
GPU_OPERATOR_VERSION="v25.10.0"
GPU_INSTALL_DRIVER=True # False for AWS
GPU_ENABLE_NFD=False # True for AWS
MPI_OPERATOR_VERSION="v0.7.0"
CONFIG_DIR=$(pwd)/gpu/cfg
PYTHON_SCRIPT_FILE=$(pwd)/gpu/main.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure \
  --config_dir $CONFIG_DIR \
  --network_operator_version ${NETWORK_OPERATOR_VERSION:-""} \
  --gpu_operator_version ${GPU_OPERATOR_VERSION:-""} \
  --gpu_install_driver ${GPU_INSTALL_DRIVER:-"True"} \
  --gpu_enable_nfd ${GPU_ENABLE_NFD:-"False"} \
  --mpi_operator_version ${MPI_OPERATOR_VERSION:-""} \
  --efa_operator_version ${EFA_OPERATOR_VERSION:-""}
```

## Execute

```bash
TOPOLOGY_VM_SIZE="ndv5"
CLOUD="azure"
RUN_ID="test"
RESULT_DIR=/tmp/${RUN_ID}
NCCL_TESTS_VERSION="amd64" # Set to "amd64" or "arm64"
mkdir -p $RESULT_DIR
PYTHON_SCRIPT_FILE=$(pwd)/gpu/main.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
  --provider $CLOUD \
  --config_dir $CONFIG_DIR \
  --result_dir $RESULT_DIR \
  --gpu_node_count 2 \
  --gpu_allocatable 1 \
  --ib_allocatable 1 \
  --topology_vm_size ${TOPOLOGY_VM_SIZE:-""} \
  --nccl_tests_version ${NCCL_TESTS_VERSION:-"amd64"}
```

## Collect

```bash
CLOUD_INFO=$CLOUD
RUN_URL="https://example.com"
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
  --result_dir $RESULT_DIR \
  --run_id $RUN_ID \
  --run_url $RUN_URL \
  --cloud_info "$CLOUD_INFO" \
  --nccl_tests_version ${NCCL_TESTS_VERSION:-"amd64"}
```
