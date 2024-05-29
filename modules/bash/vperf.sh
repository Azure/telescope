#!/bin/bash

# Function to setup the cluster and create a pod
execute_pod() {
    # Create a file named virtual-node.yaml
    cat << EOF > virtual-node.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aci-helloworld
spec:
  replicas: 1
  selector:
    matchLabels:
      app: aci-helloworld
  template:
    metadata:
      labels:
        app: aci-helloworld
    spec:
      containers:
      - name: aci-helloworld
        image: mcr.microsoft.com/azuredocs/aci-helloworld
        ports:
        - containerPort: 80
EOF

    # Apply the Kubernetes configuration
    kubectl apply -f virtual-node.yaml || {
        echo "Failed to apply Kubernetes configuration"
        exit 1
    }
}





# Function to collect results
collect_result() {
    local namespace="default"
    local result_dir=$1
    local run_url=$2

    # Ensure the result directory exists
    mkdir -p $result_dir

    # Measure the time it takes for the pod to reach the ready state
    start_time=$(kubectl -n ${namespace} get pods -o yaml | yq e '.items[].status.conditions[] | select(.type == "PodScheduled") | .lastTransitionTime' -)
    end_time=$(kubectl -n ${namespace} get pods -o yaml | yq e '.items[].status.conditions[] | select(.type == "Ready") | .lastTransitionTime' -)
    execution_time=$(( $(date -d "$end_time" "+%s") - $(date -d "$start_time" "+%s") ))
    echo "Pod reached ready state in $execution_time seconds"

    # Collect results
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local data=$(jq --null-input \
        --arg timestamp "$timestamp" \
        --arg execution_time "$execution_time" \
        --arg run_url "$run_url" \
        '{timestamp: $timestamp, execution_time: $execution_time, run_url: $run_url}')

    echo $data >> $result_dir/results.json
}
