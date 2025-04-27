# Running Kubelet Benchmark Locally

For development, you can run the test on your own cluster and observe how the cluster / workload behaves. preferrable a cluster with 2 node pools, 1 system mode and 1 agent mode.

```bash
export NODE_LABEL=kubelet-benchmark #usually the scenario name

# setup ~/.kube/config, back up existing if you need
mv ~/.kube/config ~/.kube/config.bak 
az aks get-credentials ...
# label nodes to run test
k label node <node-name> ${NODE_LABEL}=true
# taint node as done in setup
k taint node <node-name> ${NODE_LABEL}=true:NoSchedule
k taint node <node-name> ${NODE_LABEL}=true:NoExecute
# label nodes to run prometheus
k label node <another-node-name> prometheus=true

```

To run the test,

Ensure Python 3.x is installed on your system. Following the [execute.yaml](../../../../steps/engine/clusterloader2/kubelet-benchmark/execute.yml). Use `clusterloader2` as the root directory.


```bash
# setup python 
pip install -r ${REPO_ROOT}/modules/python/requirements.txt
export PYTHONPATH=$(pwd):$PYTHONPATH

export REPO_ROOT=$(git rev-parse --show-toplevel)
export NODE_LABEL=kubelet-benchmark #usually the scenario name
export NODE_COUNT=3 # adjust to your own cluster size, matching those labeled by kubelet-benchmark=true

# use full path

export PYTHONPATH=$PYTHONPATH:$(pwd):${REPO_ROOT}/modules/python
export PYTHON_SCRIPT_FILE=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/kubelet_benchmark.py
export CL2_CONFIG_DIR=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/config
export CL2_REPORT_DIR=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/results
export TEST_RESULTS_FILE=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/results/results.json

export CLOUD=aks
export MAX_PODS=30
export OPERATION_TIMEOUT=5m
export LOAD_TYPE=memory
export LOAD_FACTOR=guaranteed #choose among best_effort, burstable matching pod QoS 
export LOAD_DURATION=spike #choose among spike, normal, and long, speed of consume the resource
export CL2_IMAGE=ghcr.io/azure/clusterloader2:v20250311
export EVICTION_THRESHOLD_MEM=750Mi #default is 100Mi after k8s 1.29

echo "Running eviction benchmark"

echo "Python script file:   $PYTHON_SCRIPT_FILE"
echo "Node label:           $NODE_LABEL"
echo "CL2 config dir:       $CL2_CONFIG_DIR"
echo "CL2 report dir:       $CL2_REPORT_DIR"
echo "Cloud:                $CLOUD"
echo "Kubeconfig:           ${HOME}/.kube/config"

echo "Generating clusterloader2 override config"
echo "Node count:           $NODE_COUNT"
echo "Max pods:             $MAX_PODS"
echo "Operation timeout:    $OPERATION_TIMEOUT"
echo "Load type:            $LOAD_TYPE"
echo "Load factor:          $LOAD_FACTOR"
echo "Load duration:        $LOAD_DURATION"
```

``` bash
# generate overrides.yaml for clusterloader2 
python3 $PYTHON_SCRIPT_FILE override \
"$NODE_LABEL" "$CL2_CONFIG_DIR" "$CL2_REPORT_DIR" "$CLOUD" "${HOME}/.kube/config" \
"$NODE_COUNT" "$MAX_PODS" "$OPERATION_TIMEOUT" "$LOAD_TYPE" "$LOAD_FACTOR" "$LOAD_DURATION"
```

you can find the generated file under [config folder](config/)

```bash
# if running on macos, this is to workaround docker client
sudo ln -s "$HOME/.docker/run/docker.sock" /var/run/docker.sock

# run cluster loader2 on local cluster
python3 "$PYTHON_SCRIPT_FILE" execute \
"$NODE_LABEL" "$CL2_CONFIG_DIR" "$CL2_REPORT_DIR" "$CLOUD" "${HOME}/.kube/config" \
"$CL2_IMAGE" "$EVICTION_THRESHOLD_MEM"
```
To view metrics using embedded prometheus / grafana

```bash
# prometheus
kubectl  port-forward svc/prometheus-k8s 9090:9090 -n monitoring

# grafana
kubectl  port-forward svc/grafana 3000:3000 -n monitoring
```
Use [`local_run.sh`](./local_run.sh) to continuously run the test and collect metrics. This is useful for long-running tests.



Results are stored as `junit.xml` and its status should be `success`. Measurements are collected as `json` files.

To verify the collect step, choose a `RUN_ID` and `RUN_URL`

```bash
export RUN_URL=123
export RUN_ID=1

python3 "$PYTHON_SCRIPT_FILE" collect \
 "$NODE_LABEL" "$CL2_CONFIG_DIR" "$CL2_REPORT_DIR" "$CLOUD" "${HOME}/.kube/config" \
 "$NODE_COUNT" "$MAX_PODS" "$LOAD_TYPE" "$LOAD_FACTOR" "$LOAD_DURATION" "$EVICTION_THRESHOLD_MEM" "$RUN_ID" "$RUN_URL" "$TEST_RESULTS_FILE"

```

## Development

When making code changes, run housekeeping command:

```bash
# linting
pylint --rcfile=/Users/bh/work/telescope/.pylintrc ${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark

# unit testing
cd  ${REPO_ROOT}/modules/python/tests/clusterloader2
python3 -m unittest kubelet_benchmark/test_kubelet_benchmark.py
```
