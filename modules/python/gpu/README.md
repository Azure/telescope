# Overview

## Configure

The example below installs 3 operatiors: network operator, gpu operator, and mpi operator. To install only specific operator(s), you can set the version for that specific operator only and leave the rest unset.

```bash
pushd modules/python
NETWORK_OPERATOR_VERSION="v25.4.0"
GPU_OPERATOR_VERSION="v25.3.1"
MPI_OPERATOR_VERSION="v0.6.0"
CONFIG_DIR=$(pwd)/gpu/config
PYTHON_SCRIPT_FILE=$(pwd)/gpu/gpu.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure \
  --network_operator_version ${NETWORK_OPERATOR_VERSION:-""} \
  --gpu_operator_version ${GPU_OPERATOR_VERSION:-""} \
  --mpi_operator_version ${MPI_OPERATOR_VERSION:-""} \
  --config_dir $CONFIG_DIR
```

## Execute

```bash
VM_SIZE="ndv4"
CLOUD="azure"
RESULT_DIR=/tmp/${RUN_ID}
mkdir -p $RESULT_DIR
PYTHON_SCRIPT_FILE=$(pwd)/gpu/gpu.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
  --provider $CLOUD \
  --config_dir $CONFIG_DIR \
  --result_dir $RESULT_DIR \
  --vm_size ${VM_SIZE:-""}
```

## Collect

```bash
CLOUD_INFO=$CLOUD
RUN_URL="https://example.com"
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
  --result_dir $RESULT_DIR \
  --run_url $RUN_URL \
  --cloud_info "$CLOUD_INFO"
```
