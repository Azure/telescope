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

# Define the function to deploy a sample app
deploy_sample_app() {

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
      nodeSelector:
        kubernetes.io/role: agent
        beta.kubernetes.io/os: linux
        type: virtual-kubelet
      tolerations:
      - key: virtual-kubelet.io/provider
        operator: Exists
      - key: azure.com/aci
        effect: NoSchedule
EOF

    run_kubectl_command "apply -f virtual-node.yaml"

    run_kubectl_command "get pods -o wide"
}

# Define the function to setup cluster, deploy app and get pods
setup_deploy_and_get_pods() {
    local resource_group=$1
    local aks_cluster=$2
    local addons=$3
    local subnet_name=$4

    # Start the timer
    start_time=$(date +%s)

    # Setup cluster
    setup_cluster $resource_group $aks_cluster $addons $subnet_name

    # Deploy sample app
    deploy_sample_app

    # Stop the timer
    end_time=$(date +%s)
    execution_time=$(expr $end_time - $start_time)
    echo "Deployment completed in $execution_time seconds"
}
