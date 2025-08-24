# Overview

## Validate

```bash
pushd modules/python
KWOK_SCRIPT_FILE=$(pwd)/kwok/kwok.py
NODE_COUNT=2000
NODE_GPU=8

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $KWOK_SCRIPT_FILE \
    --action create \
    --node-count $NODE_COUNT \
    --node-gpu ${NODE_GPU:-\"0\"}

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $KWOK_SCRIPT_FILE \
    --action validate \
    --node-count $NODE_COUNT
```

## Execute

```bash
NODE_COUNT=2000
JOB_THROUGHPUT=800
JOB_COUNT=20000
JOB_TEMPLATE_PATH=gpu/job_template.yaml
SCALE_TIMEOUT="30m"
JOB_GPU=8
CLOUD=aks

PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/job_controller/job_controller.py
CL2_CONFIG_DIR=$(pwd)/clusterloader2/job_controller/config
CL2_REPORT_DIR=$(pwd)/clusterloader2/job_controller/report
CL2_IMAGE=ghcr.io/azure/clusterloader2:v20250513

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure \
    --node_count $NODE_COUNT \
    --job_throughput $JOB_THROUGHPUT \
    --job_count $JOB_COUNT \
    --job_template_path ${JOB_TEMPLATE_PATH:-job_template.yaml} \
    --operation_timeout $SCALE_TIMEOUT \
    --prometheus_enabled ${PROMETHEUS_ENABLED:-False} \
    --dra_enabled ${ENABLE_DRA:-False} \
    --job_gpu ${JOB_GPU:-0} \
    --cl2_override_file ${CL2_CONFIG_DIR}/overrides.yaml

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
    --cl2_image ${CL2_IMAGE} \
    --cl2_config_dir ${CL2_CONFIG_DIR} \
    --cl2_report_dir $CL2_REPORT_DIR \
    --prometheus_enabled ${PROMETHEUS_ENABLED:-False} \
    --kubeconfig ${HOME}/.kube/config \
    --provider $CLOUD
```

## Collect

```bash
CLOUD_INFO=$CLOUD
RUN_URL=http://example.com
RUN_ID=123456789
mkdir -p /tmp/${RUN_ID}
TEST_RESULTS_FILE=/tmp/${RUN_ID}/results.json

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
    --node_count $NODE_COUNT \
    --job_throughput $JOB_THROUGHPUT \
    --job_count $JOB_COUNT \
    --dra_enabled ${ENABLE_DRA:-False} \
    --job_gpu ${JOB_GPU:-0} \
    --cl2_report_dir $CL2_REPORT_DIR \
    --cloud_info "$CLOUD_INFO" \
    --run_id $RUN_ID \
    --run_url $RUN_URL \
    --result_file $TEST_RESULTS_FILE

PYTHONPATH=$PYTHONPATH:$(pwd) python3 $KWOK_SCRIPT_FILE \
    --action tear_down \
    --node-count $NODE_COUNT
```
