#!/bin/bash

set -eo pipefail

export REPO_ROOT=$(git rev-parse --show-toplevel)
export PYTHONPATH=$(pwd):$PYTHONPATH
export NODE_LABEL=kubelet-benchmark #usually the scenario name
export NODE_COUNT=3 # adjust to your own cluster size, matching those labeled by kubelet-benchmark=true
export PYTHONPATH=$PYTHONPATH:$(pwd):${REPO_ROOT}/modules/python
export PYTHON_SCRIPT_FILE=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/kubelet_benchmark.py
export CL2_CONFIG_DIR=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/config
export CL2_REPORT_DIR=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/results
export TEST_RESULTS_FILE=${REPO_ROOT}/modules/python/clusterloader2/kubelet_benchmark/results/results.json

export CLOUD=aks
export MAX_PODS=12
export OPERATION_TIMEOUT=10m
export LOAD_TYPE=rampup #choose among multiworker, rampup, and seesaw
export LOAD_FACTOR=guaranteed #choose among best_effort, burstable matching pod QoS
export LOAD_DURATION=spike #choose among spike, normal, and long, speed of consume the resource
export CL2_IMAGE=ghcr.io/azure/clusterloader2:v20250311
export EVICTION_THRESHOLD_MEM=100Mi #default is 100Mi after k8s 1.29
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

# generate overrides.yaml for clusterloader2
# echo "generating overrides.yaml"
python3 $PYTHON_SCRIPT_FILE override \
"$NODE_LABEL" "$CL2_CONFIG_DIR" "$CL2_REPORT_DIR" "$CLOUD" "${HOME}/.kube/config" \
"$NODE_COUNT" "$MAX_PODS" "$OPERATION_TIMEOUT" "$LOAD_TYPE" "$LOAD_FACTOR" "$LOAD_DURATION"

# Start time
start_time=$(date +%s)

# Run duration in seconds (30 minutes)
run_duration=$((30 * 60))


while true; do
  # Get the current time
  current_time=$(date +%s)

  # Check if the total run duration has been exceeded
  if (( current_time - start_time >= run_duration )); then
    echo "Execution completed. Total duration: 1 hour."
    break
  fi

  # Run the execute command
  echo "Running execute command..."
  python3 "$PYTHON_SCRIPT_FILE" execute \
    "$NODE_LABEL" "$CL2_CONFIG_DIR" "$CL2_REPORT_DIR" "$CLOUD" "${HOME}/.kube/config" \
    "$CL2_IMAGE" "$EVICTION_THRESHOLD_MEM"
  # Wait for 2 minutes before the next run
  echo "Waiting for 2 minutes before the next run..."
  sleep 120
done