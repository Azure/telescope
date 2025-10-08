# Overview

## Validate

```bash
cd modules/python
PYTHON_SCRIPT_FILE=$(pwd)/fio/fio.py
DESIRED_NODES=7
VALIDATION_TIMEOUT_IN_MINUTES=1
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE validate \
    $DESIRED_NODES $VALIDATION_TIMEOUT_IN_MINUTES
```

### Configure acstor-v2

```bash
helm install local-csi-driver oci://localcsidriver.azurecr.io/acstor/charts/local-csi-driver --version 0.2.5 \
    --namespace local-csi-system --create-namespace --wait --atomic
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=local-csi-driver -n local-csi-system --timeout=600s
kustomize build configuration | kubectl apply -f -
kubectl get storageclass local
kubectl get pods -n local-csi-system
```

## Execute

```bash
FIO_PROPERTY="128k|16|write|600|16|32G"
fio_params=(${FIO_PROPERTY//|/ })
block_size=${fio_params[0]}
iodepth=${fio_params[1]}
method=${fio_params[2]}
runtime=${fio_params[3]}
numjobs=${fio_params[4]}
file_size=${fio_params[5]}

RESULT_DIR=/tmp/${RUN_ID}
mkdir -p $RESULT_DIR
STORAGE_NAME=acstor-v2
KUSTOMIZE_DIR=$(pwd)/modules/kustomize/fio

pushd modules/python
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
    --block_size $block_size \
    --iodepth $iodepth \
    --method $method \
    --runtime $runtime \
    --numjobs $numjobs \
    --file_size $file_size \
    --storage_name $STORAGE_NAME \
    --kustomize_dir $KUSTOMIZE_DIR \
    --result_dir $RESULT_DIR
```

