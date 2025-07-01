# CRI Performance Testing

Instructions on how to run CRI test manually

## Provision resources

Follow one of the below guides to provision resources in corresponding cloud

- [Guide](../../../terraform/azure/README.md) for Azure resources
- [Guide](../../../terraform/aws/README.md) for AWS resources

Variables specific to this scenarios:

```bash
SCENARIO_TYPE=perf-eval
SCENARIO_NAME=cri-resource-consume
RUN_ID=$(date +%s)
CLOUD=azure # aws if provision AWS resources
REGION=swedencentral # eu-west-1 if provision AWS resources
KUBERNETES_VERSION=1.31 # customize for different version, only available for Azure currently
K8S_MACHINE_TYPE=Standard_D16ds_v4 # if not set, value defined in tfvars file will be used, only availabe for Azure currently
K8S_OS_DISK_TYPE=Ephemeral # if not set, value defined in tfvars file will be used, only available for Azure currently
TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
```

## Validate resources

Get credentials to access cluster

- For AKS:

```bash
az aks get-credentials -n cri-resource-consume -g $RUN_ID
```

- For EKS:

```bash
aws eks update-kubeconfig --name "cri-resource-consume-${RUN_ID}" --region $REGION
```

Run following commands to validate node count (remember to run in `root` directory)

```bash
cd modules/python
DESIRED_NODES=14
VALIDATION_TIMEOUT_IN_MINUTES=10
PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/slo/slo.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE validate \
    $DESIRED_NODES $VALIDATION_TIMEOUT_IN_MINUTES
```

## Execute test

Set these variables before running the test:

```bash
PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/cri/cri.py
NODE_COUNT=10
MAX_PODS=30
REPEATS=1
OPERATION_TIMEOUT="3m"
LOAD_TYPE="memory"
POD_STARTUP_LATENCY_THRESHOLD="15s"
CL2_CONFIG_DIR=$(pwd)/clusterloader2/cri/config
CL2_IMAGE="ghcr.io/azure/clusterloader2:v20250513"
CL2_REPORT_DIR=$(pwd)/clusterloader2/cri/results
CLOUD=aks # set to aws to run against aws
SCRAPE_KUBELETS=True
OS_TYPE="linux"
# NODE_PER_STEP=5
# SCALE_ENABLED=True
```

**Note**:

- `SCRAPE_KUBELETS` is not suggested to used together with scaling when these 2 variables `NODE_PER_STEP` and `SCALE_ENABLED` are set.
- For scaling test, you should always start with 1 node and set total node count to be desired scale count + 1. For example, when scaling 100 nodes, the `NODE_COUNT` should be set to 101.
- Different clouds have different number of default daemonsets. So the actual pods deployed in the test will be slightly different across clouds, but total pods per node (including daemonsets) should be the same.

Run these commands to execute test:

```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE override \
    --node_count $NODE_COUNT \
    --node_per_step ${NODE_PER_STEP:-$NODE_COUNT} \
    --max_pods $MAX_PODS \
    --repeats $REPEATS \
    --operation_timeout $OPERATION_TIMEOUT \
    --load_type $LOAD_TYPE \
    --scale_enabled ${SCALE_ENABLED:-False} \
    --pod_startup_latency_threshold ${POD_STARTUP_LATENCY_THRESHOLD:-15s} \
    --provider $CLOUD \
    --os_type ${OS_TYPE:-linux} \
    --scrape_kubelets ${SCRAPE_KUBELETS:-False} \
    --cl2_override_file ${CL2_CONFIG_DIR}/overrides.yaml
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
    --cl2_image ${CL2_IMAGE} \
    --cl2_config_dir ${CL2_CONFIG_DIR} \
    --cl2_report_dir $CL2_REPORT_DIR \
    --kubeconfig ${HOME}/.kube/config \
    --provider $CLOUD \
    --scrape_kubelets ${SCRAPE_KUBELETS:-False}
```

Raw result can be found in folder `CL2_REPORT_DIR`

## Collect result

Set dummy variables:

```bash
CLOUD_INFO=$CLOUD
RUN_URL=123
TEST_RESULTS_FILE=$(pwd)/results.json
```

Run collect command:

```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
    --node_count $NODE_COUNT \
    --max_pods $MAX_PODS \
    --repeats $REPEATS \
    --load_type $LOAD_TYPE \
    --cl2_report_dir $CL2_REPORT_DIR \
    --cloud_info "$CLOUD_INFO" \
    --run_id $RUN_ID \
    --run_url $RUN_URL \
    --result_file $TEST_RESULTS_FILE \
    --scrape_kubelets ${SCRAPE_KUBELETS:-False}
```

The final result which will be used to upload to storage account will be in this file `TEST_RESULTS_FILE`

## Clean up resources

Follow guide in [Provision resources](#provision-resources) step to clean up once you're done.
