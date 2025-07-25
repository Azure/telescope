# Overview

## Execute

```bash
pushd modules/python
NETWORK_OPERATOR_VERSION="v25.4.0"
GPU_OPERATOR_VERSION="v25.3.1"
MPI_OPERATOR_VERSION="v0.6.0"
CONFIG_DIR=$(pwd)/../kustomize
PYTHON_SCRIPT_FILE=$(pwd)/gpu/gpu.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure \
  --network_operator_version $NETWORK_OPERATOR_VERSION \
  --gpu_operator_version $GPU_OPERATOR_VERSION \
  --mpi_operator_version $MPI_OPERATOR_VERSION \
  --config_dir $CONFIG_DIR
```
