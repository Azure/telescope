#!/usr/bin/env bash

init() {
    AZ=/usr/bin/az

    SCENARIO_TYPE=perf-eval
    SCENARIO_NAME=slo-servicediscovery
    OWNER=$(whoami)
    RUN_ID=32633-dbb72cb6-fa09-5b75-bf70-9a218c54fc1a
    CLOUD=azure
    REGION=us-east-1
    KUBERNETES_VERSION=1.31
    SKU_TIER=Standard    
    TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
    TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
    K8S_MACHINE_TYPE=Standard_D16ds_v4 # if not set, value defined in tfvars file will be used, only availabe for Azure currently
    K8S_OS_DISK_TYPE=Ephemeral # if not set, value defined in tfvars file will be used, only available for Azure currently
    SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
    USER_NODE_POOL=${USER_NODE_POOL:-null}

    CL2_CONFIG_DIR=$(pwd)/clusterloader2/cri/config
    CL2_IMAGE="ghcr.io/azure/clusterloader2:v20250513"
    CL2_REPORT_DIR=$(pwd)/clusterloader2/cri/results

    CPU_PER_NODE=4
    NODE_COUNT=1000
    NODE_PER_STEP=1000
    MAX_PODS=20
    REPEATS=10
    SCALE_TIMEOUT="15m"
    CILIUM_ENABLED=False
    SCRAPE_CONTAINERD=True
    SERVICE_TEST=True
    CL2_CONFIG_FILE=load-config.yaml
    TOPOLOGY=service-churn

    INPUT_JSON=$(jq -n \
    --arg run_id $RUN_ID \
    --arg region $REGION \
    --arg aks_sku_tier "$SKU_TIER" \
    --arg aks_kubernetes_version "$KUBERNETES_VERSION" \
    --arg aks_network_policy "$NETWORK_POLICY" \
    --arg aks_network_dataplane "$NETWORK_DATAPLANE" \
    --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
    --arg k8s_os_disk_type "$K8S_OS_DISK_TYPE" \
    --argjson aks_cli_system_node_pool "$SYSTEM_NODE_POOL" \
    --argjson aks_cli_user_node_pool "$USER_NODE_POOL" \
    '{
        run_id: $run_id,
        region: $region,
        aks_sku_tier: $aks_sku_tier,
        aks_kubernetes_version: $aks_kubernetes_version,
        aks_network_policy: $aks_network_policy,
        aks_network_dataplane: $aks_network_dataplane,
        k8s_machine_type: $k8s_machine_type,
        k8s_os_disk_type: $k8s_os_disk_type,
        aks_cli_system_node_pool: $aks_cli_system_node_pool,
        aks_cli_user_node_pool: $aks_cli_user_node_pool
    }' | jq 'with_entries(select(.value != null and .value != ""))')

    export PYTHONPATH=$(pwd)/modules/python/:${PYTHONPATH:-.}
}

setup_cluster() {
    $AZ login

    $AZ account set --subscription c0d4b923-b5ea-4f8f-9b56-5390a9bf2248 # Telescope Open Source
    export ARM_SUBSCRIPTION_ID=$($AZ account show --query id -o tsv | tr -d '\r')

    $AZ group create --name $RUN_ID \
        --location $REGION \
        --tags  "run_id=$RUN_ID" \
                "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" \
                "owner=${OWNER}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
                "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"

    pushd $TERRAFORM_MODULES_DIR
    terraform init
    terraform plan -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
    terraform apply -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
    popd
    
    $AZ aks get-credentials -n $SCENARIO_NAME -g $RUN_ID
}

teardown_cluster() {
    pushd $TERRAFORM_MODULES_DIR

    terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE

    popd
}

slo_validate() {
    pushd modules/python

    DESIRED_NODES=14
    VALIDATION_TIMEOUT_IN_MINUTES=10
    PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/slo/slo.py

    python3 $PYTHON_SCRIPT_FILE validate \
            $DESIRED_NODES \
            $VALIDATION_TIMEOUT_IN_MINUTES

    popd
}

slo_configure_and_execute() {
    pushd modules/python

    python3 $PYTHON_SCRIPT_FILE configure \
                                $CPU_PER_NODE \
                                $NODE_COUNT \
                                $NODE_PER_STEP \
                                ${MAX_PODS:-0} \
                                $REPEATS \
                                $SCALE_TIMEOUT \
                                $CLOUD \
                                $CILIUM_ENABLED \
                                ${SCRAPE_CONTAINERD:-False} \
                                $SERVICE_TEST \
                                ${CL2_CONFIG_DIR}/overrides.yaml

    python3 $PYTHON_SCRIPT_FILE execute \
                                ${CL2_IMAGE} \
                                ${CL2_CONFIG_DIR} \
                                $CL2_REPORT_DIR \
                                $CL2_CONFIG_FILE \
                                ${HOME}/.kube/config \
                                $CLOUD \
                                ${SCRAPE_CONTAINERD:-False}

    popd
}

main() {
    init
    setup_cluster
    slo_validate
    slo_configure_and_execute
    teardown_cluster
}

main
