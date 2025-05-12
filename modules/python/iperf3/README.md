# Running iperf3 locally

## Configure MTU (optional)

From root folder, run the following commands to update MTU value in Azure v6 machine type and configure ENA Express for AWS m7i machine type:

```bash
CLOUD=azure # or aws
CLUSTER_CLI_CONTEXT=pod-diff-node
CLUSTER_SRV_CONTEXT=pod-diff-node
KUSTOMIZE_DIR=$(pwd)/modules/kustomize/mtu
pushd $KUSTOMIZE_DIR
kustomize build overlays/${CLOUD} | kubectl --context=$CLUSTER_CLI_CONTEXT apply -f -
kustomize build overlays/${CLOUD} | kubectl --context=$CLUSTER_SRV_CONTEXT apply -f -
popd

pushd modules/python
PYTHON_SCRIPT_FILE=$(pwd)/iperf3/iperf3_pod.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure --pod_count 1 --label_selector "app=mtu-config"
popd
```

## Configure iperf3

From root folder, run the following command to deploy iperf3:

```bash
HOST_NETWORK=false # or true
CLUSTER_CLI_CONTEXT=pod-diff-node
CLUSTER_SRV_CONTEXT=pod-diff-node
KUSTOMIZE_DIR=$(pwd)/modules/kustomize/iperf3
KUSTOMIZE_DIR=$(pwd)/iperf3
pushd $KUSTOMIZE_DIR
kustomize build ${KUSTOMIZE_DIR}/overlays/client-hostnetwork-${HOST_NETWORK} | kubectl --context=$CLUSTER_CLI_CONTEXT apply -f -
kustomize build ${KUSTOMIZE_DIR}/overlays/server-hostnetwork-${HOST_NETWORK} | kubectl --context=$CLUSTER_SRV_CONTEXT apply -f -
popd

pushd modules/python
PYTHON_SCRIPT_FILE=$(pwd)/iperf3/iperf3_pod.py
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE configure --pod_count 1
popd
```

## Validation

From root folder, run:

```bash
cd modules/python
CLOUD=azure
PYTHON_SCRIPT_FILE=$(pwd)/iperf3/iperf3_pod.py
CLUSTER_CLI_CONTEXT=pod-diff-node
CLUSTER_SRV_CONTEXT=pod-diff-node
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE validate \
    --cluster_cli_context "$CLUSTER_CLI_CONTEXT" \
    --cluster_srv_context "$CLUSTER_SRV_CONTEXT"
```

## Execute

For each execute input, run:

```bash
RUN_ID=$(date +%s)
index="1"
protocol="tcp"
bandwidth="1000"
concurrency="1"
iperf_command="--time 60 --bandwidth 1000M --parallel 1 --interval 0 --port 20003"
datapath="direct"
server_ip_type="pod"
RESULT_DIR=/tmp/${RUN_ID}
mkdir -p $RESULT_DIR
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE run_benchmark \
    --index "$index" \
    --protocol "$protocol" \
    --bandwidth "$bandwidth" \
    --parallel "$concurrency" \
    --iperf_command "$iperf_command" \
    --datapath "$datapath" \
    --result_dir "$RESULT_DIR" \
    --cluster_cli_context "$CLUSTER_CLI_CONTEXT" \
    --cluster_srv_context "$CLUSTER_SRV_CONTEXT" \
    --server_ip_type "$server_ip_type"
```

## Collect

Run once to collect pod and node information:

```bash
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect_pod_node_info \
    --result_dir "$RESULT_DIR" \
    --cluster_cli_context "$CLUSTER_CLI_CONTEXT" \
    --cluster_srv_context "$CLUSTER_SRV_CONTEXT"
```

Run the same number of times you run execute command for different inputs:

```bash
RUN_URL="https://localhost:8080"
RESULT_FILE="$RESULT_DIR/results.json"
PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
    --result_dir "$RESULT_DIR" \
    --result_file "$RESULT_FILE" \
    --cloud_info "$CLOUD" \
    --run_url "$RUN_URL" \
    --protocol "$protocol" \
    --bandwidth "$bandwidth" \
    --parallel "$concurrency" \
    --datapath "$datapath" \
    --index "$index"
```
