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
}

# Define the function to setup cluster, create pod and get pods
setup_create_and_get_pods() {
    local resource_group=$1
    local aks_cluster=$2
    local addons=$3
    local subnet_name=$4
    local namespace="default" # Pods will be created in the default namespace

    # Setup cluster
    setup_cluster $resource_group $aks_cluster $addons $subnet_name

    # Create pod
    create_pod

    # Measure the time it takes for the pod to reach the ready state
    start_time=$(kubectl -n ${namespace} get pods -o yaml | yq e '.items[].status.conditions[] | select(.type == "PodScheduled") | .lastTransitionTime' -)
    end_time=$(kubectl -n ${namespace} get pods -o yaml | yq e '.items[].status.conditions[] | select(.type == "Ready") | .lastTransitionTime' -)
    execution_time=$(echo $(( $(date -d "$end_time" "+%s") - $(date -d "$start_time" "+%s") )))
    echo "Pod reached ready state in $execution_time seconds"
}
