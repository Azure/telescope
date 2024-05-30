#!/bin/bash

# Function to setup the cluster and create a pod
create_pod() {
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

    # Apply the Kubernetes configuration for warm-up
    echo "Starting warm-up deployment..."
    kubectl apply -f virtual-node.yaml || {
        echo "Failed to apply Kubernetes configuration for warm-up"
        exit 1
    }

    # Wait for the pod to be ready
    echo "Waiting for the pod to be ready..."
    kubectl wait --for=condition=ready pod -l app=aci-helloworld --timeout=120s || {
        echo "Pod did not reach ready state in warm-up"
        exit 1
    }

    # Delete the warm-up deployment
    echo "Deleting the warm-up deployment..."
    kubectl delete -f virtual-node.yaml || {
        echo "Failed to delete the warm-up deployment"
        exit 1
    }

    # Sequentially deploy 10 pods
    for i in {1..10}; do
        deployment_name="aci-helloworld-$i"
        
        cat << EOF > virtual-node-${i}.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${deployment_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${deployment_name}
  template:
    metadata:
      labels:
        app: ${deployment_name}
    spec:
      containers:
      - name: aci-helloworld
        image: mcr.microsoft.com/azuredocs/aci-helloworld
        ports:
        - containerPort: 80
EOF

        echo "Starting deployment $i..."
        kubectl apply -f virtual-node-${i}.yaml || {
            echo "Failed to apply Kubernetes configuration for deployment $i"
            exit 1
        }

        # Wait for the pod to be ready
        echo "Waiting for the pod $i to be ready..."
        kubectl wait --for=condition=ready pod -l app=${deployment_name} --timeout=120s || {
            echo "Pod $i did not reach ready state"
            exit 1
        }

        echo "Deployment $i is ready"
    done

    echo "All pods have been deployed successfully"
}

# Function to collect results
collect_result() {
    local namespace="default"
    local result_dir=$1
    local run_url=$2

    # Ensure the result directory exists
    mkdir -p $result_dir

    # Initialize an array to store individual pod deployment times
    pod_times=()
    
    for i in {1..10}; do
        deployment_name="aci-helloworld-$i"
        
        # Measure the time it takes for the pod to reach the ready state
        start_time=$(kubectl -n ${namespace} get pods -l app=${deployment_name} -o jsonpath='{.items[*].status.conditions[?(@.type=="PodScheduled")].lastTransitionTime}')
        end_time=$(kubectl -n ${namespace} get pods -l app=${deployment_name} -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].lastTransitionTime}')
        
        start_time_epoch=$(date -d"$start_time" +%s.%N)
        end_time_epoch=$(date -d"$end_time" +%s.%N)
        
        execution_time=$(echo "$end_time_epoch - $start_time_epoch" | bc)
        echo "Pod $i reached ready state in $execution_time seconds"
        
        # Add the execution time to the array
        pod_times+=("$execution_time")
        
        # Collect result for this pod
        local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        local data=$(jq --null-input \
            --arg pod "aci-helloworld-$i" \
            --arg timestamp "$timestamp" \
            --arg execution_time "$execution_time" \
            '{pod: $pod, timestamp: $timestamp, execution_time: $execution_time}')
        
        echo $data >> $result_dir/results.json
    done

    # Calculate the average deployment time
    total_time=0
    for time in "${pod_times[@]}"; do
        total_time=$(echo "$total_time + $time" | bc)
    done
    average_time=$(echo "$total_time / ${#pod_times[@]}" | bc -l)
    echo "Average deployment time: $average_time seconds"

    # Append the average deployment time to the results file
    local avg_data=$(jq --null-input \
        --arg average_time "$average_time" \
        '{average_execution_time: $average_time}')
    
    echo $avg_data >> $result_dir/results.json
}
