# Overview

The CRUD module provides comprehensive node pool management operations for Kubernetes clusters across multiple cloud providers (Azure, AWS). It supports creating, scaling, deleting node pools, and collecting benchmark results from CRUD operations.

## Prerequisite

* Install [Terraform - 1.7.3](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli)
* Install [Azure CLI - 2.57.0](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
* Install [jq - 1.6-2.1ubuntu3](https://stedolan.github.io/jq/download/)

## Supported Operations

* **create**: Create a new node pool
* **scale**: Scale an existing node pool up or down
* **delete**: Delete an existing node pool  
* **all**: Run complete lifecycle (create → scale up → scale down → delete)
* **deployment**: Create Deployments and record aggregate readiness time
* **statefulset**: Create StatefulSets and record aggregate readiness time
* **job**: Create Jobs and record aggregate completion time
* **collect**: Collect and process benchmark results

## Define Variables

### Common Variables

```bash
pushd modules/python
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

mkdir -p $RESULT_DIR
```

For Azure node-pool create and scale using shared provisioning instrumentation,
`--step-timeout` controls both the ARM timeout (SDK polling or the VirtualMachines CLI) and Kubernetes
node readiness. Progressive scaling applies this timeout to each scale step.
For example, `--step-timeout 2400` allows a 40-minute operation on either pool type.
The low-level provisioning helpers retain their 30-minute default when called
without a timeout override.

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
CLOUD="aws"
CAPACITY_TYPE="CAPACITY_BLOCK"
export AWS_DEFAULT_REGION="us-east-1"
```

## Create Node Pool

Create a new node pool in your Kubernetes cluster:

```bash
python3 -m crud.main create \
    --cloud $CLOUD \
    --run-id $RUN_ID \
    --result-dir "$RESULT_DIR" \
    --node-pool-name "$NODE_POOL_NAME" \
    --vm-size $VM_SIZE \
    --node-count $CREATE_NODE_COUNT \
    --step-timeout $STEP_TIME_OUT \
    --capacity-type "${CAPACITY_TYPE:-ON_DEMAND}" \
    ${GPU_NODE_POOL:+--gpu-node-pool}
```

## Scale Up Node Pool

```bash

python3 -m crud.main scale \
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
python3 -m crud.main scale \
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
python3 -m crud.main delete \
    --cloud $CLOUD \
    --run-id $RUN_ID \
    --result-dir $RESULT_DIR \
    --node-pool-name $NODE_POOL_NAME \
    --step-timeout $STEP_TIME_OUT
```

## Complete Lifecycle (All Operations)

Run the complete node pool lifecycle - create, scale up, scale down, and delete:

```bash

python3 -m crud.main all \
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

## Workload Timing

Each workload command writes one aggregate operation record to `RESULT_DIR`.
The duration covers all requested workload instances through their Available,
Ready, or Complete condition.

```bash
python3 -m crud.main deployment \
    --cloud azure \
    --run-id "$RUN_ID" \
    --result-dir "$RESULT_DIR" \
    --node-pool-name "$NODE_POOL_NAME" \
    --count 1 \
    --replicas 10 \
    --step-timeout "$STEP_TIME_OUT"

python3 -m crud.main statefulset \
    --cloud azure \
    --run-id "$RUN_ID" \
    --result-dir "$RESULT_DIR" \
    --node-pool-name "$NODE_POOL_NAME" \
    --count 1 \
    --replicas 10 \
    --step-timeout "$STEP_TIME_OUT"

python3 -m crud.main job \
    --cloud azure \
    --run-id "$RUN_ID" \
    --result-dir "$RESULT_DIR" \
    --node-pool-name "$NODE_POOL_NAME" \
    --count 1 \
    --completions 1 \
    --step-timeout "$STEP_TIME_OUT"
```

## Collect Benchmark Results

`telescope-crud collect` converts canonical operation files into final Telescope
JSONL rows. Pipeline-owned context can be passed explicitly; the equivalent
uppercase environment variables remain supported for existing callers.

By default, collection preserves the canonical `operation_info` object and
appends rows containing `timestamp`, `region`, `operation_info`, `run_id`, and
`run_url`, as before. No legacy names or pipeline context fields are added.

Internal pipelines publishing to legacy ADX consumers must explicitly opt in:

```bash
telescope-crud collect \
    --legacy-output \
    --result-dir "/tmp/${RUN_ID}" \
    --result-file "/tmp/${RUN_ID}/results.json" \
    --run-id "$RUN_ID" \
    --run-url "$RUN_URL" \
    --region "$REGION" \
    --cloud-info "$CLOUD_INFO" \
    --vm-size "$VM_SIZE" \
    --node-pool-name "$NODE_POOL_NAME" \
    --create-node-count "$CREATE_NODE_COUNT" \
    --scale-node-count "$SCALE_NODE_COUNT" \
    --node-pool-type "$NODE_POOL_TYPE" \
    --node-pool-number "$NODE_POOL_NUMBER" \
    --batch-size "$BATCH_SIZE" \
    --workload-test-setting "$WORKLOAD_TEST_SETTING"
```

`python3 -m crud.main collect` is also supported.

Explicit arguments override their environment variables. `RESULT_DIR`, `RUN_ID`,
`RUN_URL`, and `REGION` (or their CLI equivalents) are required. The output
defaults to `RESULT_DIR/results.json`. `CLOUD_INFO` / `--cloud-info` supplies a
JSON-encoded object such as `{"cloud":"azure","aks_name":"my-cluster"}`; it
defaults to `{}` when omitted. Other context fields are optional and used only
with `--legacy-output`. Node counts and batch size are published as integers;
the node-pool number retains the legacy string representation.

With `--legacy-output`, the published `operation_info` retains canonical fields such as `success`,
`duration`, timestamps, errors, and `metadata`. At the publishing boundary it
also includes the established ADX names and fields (`succeeded`, `time`, node
timings, and legacy node-pool operation names). Keeping this compatibility
adapter in the collector protects existing alerts and dashboards without
coupling CRUD execution logic to the legacy schema.

The original operation name is retained as `canonical_name`; the published
`name` maps `create_node_pool`, `scale_up`, `scale_down`, and `delete_node_pool`
to `create_agent_pool`, `scale_agent_pool`, `clean_agent_pool`, and
`delete_agent_pool`, respectively. Workload names are unchanged. `data` contains
JSON-encoded node-pool `metadata.cluster_info` (the legacy string representation)
or the workload metadata. Source files are never modified.

Legacy collection requires each source to contain an `operation_info` object with a
non-empty string `name`, boolean `success`, and object `metadata` if present.
Invalid inputs or publishing failures are logged and return a nonzero exit
code without replacing the previous output. In legacy mode, validated rows are
published by atomically replacing the output file, so rerunning collection does
not duplicate rows. Default collection retains its existing append behavior.
