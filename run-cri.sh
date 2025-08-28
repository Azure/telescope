#!/usr/bin/env bash

set -x

AZ=/usr/bin/az

init_vars() {
    SCENARIO_TYPE=perf-eval
    SCENARIO_NAME=cri-resource-consume
    OWNER=$(whoami)
    RUN_ID=$(date +%s)
    CLOUD=azure
    REGION=swedencentral
    KUBERNETES_VERSION=1.31
    NETWORK_POLICY=cilium
    NETWORK_DATAPLANE=cilium
    SKU_TIER=Standard    
    TERRAFORM_MODULES_DIR=modules/terraform/$CLOUD
    TERRAFORM_INPUT_FILE=$(pwd)/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
    K8S_MACHINE_TYPE=Standard_D16ds_v4
    K8S_OS_DISK_TYPE=Ephemeral
    SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
    USER_NODE_POOL=${USER_NODE_POOL:-null}

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
}

teardown_cluster() {
    pushd $TERRAFORM_MODULES_DIR
    terraform destroy -var json_input=$(echo $INPUT_JSON | jq -c .) -var-file $TERRAFORM_INPUT_FILE
    popd
}

teardown_resource_group() {
    $AZ group delete --name $RUN_ID -y
}

setup_resource_group() {
    $AZ group create \
        --name $RUN_ID \
        --location $REGION \
        --tags "run_id=$RUN_ID" \
               "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" \
               "owner=${OWNER}" \
               "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
               "deletion_due_time=$(date -u -d '+2 hour' +'%Y-%m-%dT%H:%M:%SZ')"
}

cri_resource_consume() {
    $AZ aks get-credentials -n $SCENARIO_NAME -g $RUN_ID

    cd modules/python
    DESIRED_NODES=14
    VALIDATION_TIMEOUT_IN_MINUTES=10
    PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/slo/slo.py

    export PYTHONPATH=$(pwd):${PYTHONPATH:-.}

    python3 $PYTHON_SCRIPT_FILE validate \
        $DESIRED_NODES $VALIDATION_TIMEOUT_IN_MINUTES

    cd modules/python
    DESIRED_NODES=14
    VALIDATION_TIMEOUT_IN_MINUTES=10
    PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/slo/slo.py
    PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE validate \
        $DESIRED_NODES $VALIDATION_TIMEOUT_IN_MINUTES

    PYTHON_SCRIPT_FILE=$(pwd)/clusterloader2/cri/cri.py
    NODE_COUNT=10
    MAX_PODS=30
    REPEATS=1
    OPERATION_TIMEOUT="3m"
    LOAD_TYPE="memory"
    POD_STARTUP_LATENCY_THRESHOLD="15s"
    CL2_CONFIG_DIR=$(pwd)/clusterloader2/cri/config
    CL2_IMAGE="ghcr.io/azure/clusterloader2:v20250513"
    CL2_REPORT_DIR=$(pwd)/clusterloader2/cri/results
    CLOUD=aks # set to aws to run against aws
    SCRAPE_KUBELETS=True
    OS_TYPE="linux"
    HOST_NETWORK=True
    # NODE_PER_STEP=5
    # SCALE_ENABLED=True

    PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE override \
        --node_count $NODE_COUNT \
        --node_per_step ${NODE_PER_STEP:-$NODE_COUNT} \
        --max_pods $MAX_PODS \
        --repeats $REPEATS \
        --operation_timeout $OPERATION_TIMEOUT \
        --load_type $LOAD_TYPE \
        --scale_enabled ${SCALE_ENABLED:-False} \
        --pod_startup_latency_threshold ${POD_STARTUP_LATENCY_THRESHOLD:-15s} \
        --provider $CLOUD \
        --os_type ${OS_TYPE:-linux} \
        --scrape_kubelets ${SCRAPE_KUBELETS:-False} \
        --host_network ${HOST_NETWORK:-True} \
        --cl2_override_file ${CL2_CONFIG_DIR}/overrides.yaml
    PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE execute \
        --cl2_image ${CL2_IMAGE} \
        --cl2_config_dir ${CL2_CONFIG_DIR} \
        --cl2_report_dir $CL2_REPORT_DIR \
        --kubeconfig ${HOME}/.kube/config \
        --provider $CLOUD \
        --scrape_kubelets ${SCRAPE_KUBELETS:-False}

    CLOUD_INFO=$CLOUD
    RUN_URL=123
    TEST_RESULTS_FILE=$(pwd)/results.json

    PYTHONPATH=$PYTHONPATH:$(pwd) python3 $PYTHON_SCRIPT_FILE collect \
        --node_count $NODE_COUNT \
        --max_pods $MAX_PODS \
        --repeats $REPEATS \
        --load_type $LOAD_TYPE \
        --cl2_report_dir $CL2_REPORT_DIR \
        --cloud_info "$CLOUD_INFO" \
        --run_id $RUN_ID \
        --run_url $RUN_URL \
        --result_file $TEST_RESULTS_FILE \
        --scrape_kubelets ${SCRAPE_KUBELETS:-False}
}

main() {
    #trap teardown_resource_group 0
    #trap teardown_cluster 0
    init_vars
    setup_resource_group
    setup_cluster
    cri_resource_consume
}

main "$@"
