#!/bin/bash

# Define the function to run kubectl commands
run_kubectl_command() {
    local command=$1

    kubectlCommand="kubectl $command"
    $kubectlCommand
}

# Define the function to enable add-ons and connect to cluster
setup_cluster() {
    local resource_group=$1
    local aks_cluster=$2
    local addons=$3
    local subnet_name=$4

    # Enable add-ons
    azure_aks_enable_addons $resource_group $aks_cluster $addons $subnet_name

    # Connect to cluster
    azure_aks_get_credentials $resource_group $aks_cluster
}

# Define the function to create a pod
create_pod() {

    # Create a file named virtual-node.yaml
    cat << EOF > virtual-node.yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  containers:
  - name: my-container
    image: nginx
    ports:
    - containerPort: 80
EOF

    run_kubectl_command "create -f virtual-node.yaml"

    run_kubectl_command "get pods -o wide"
}

# Define the function to setup cluster, create pod and get pods
setup_create_and_get_pods() {
    local resource_group=$1
    local aks_cluster=$2
    local addons=$3
    local subnet_name=$4

    # Start the timer
    start_time=$(date +%s)

    # Setup cluster
    setup_cluster $resource_group $aks_cluster $addons $subnet_name

    # Create pod
    create_pod

    # Stop the timer
    end_time=$(date +%s)
    execution_time=$(expr $end_time - $start_time)
    echo "Pod creation completed in $execution_time seconds"
}
