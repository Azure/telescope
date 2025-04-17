from textwrap import dedent
from pipeline import Script

set_input_variables_aws = lambda cloud, regions, input_variables={}: Script(
    display_name="Set Terraform Input Variables",
    script=dedent(
        """
        set -e

        if [[ "${DEBUG,,}" =~ "true" ]]; then
          set -x
        fi

        CREATION_TIME=$(date -uIseconds |  sed 's/+00:00/Z/')
        regional_config=$REGIONAL_CONFIG
        for REGION in $(echo "$REGIONS" | jq -r '.[]'); do
          if [ -z "$INPUT_VARIABLES" ]; then
            echo "Set input variables for region $REGION"
            INPUT_VARIABLES=$(jq -n \
                  --arg run_id $RUN_ID \
                  --arg region $REGION \
                  --arg creation_time $CREATION_TIME \
                  --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
                  --arg user_data_path "$TERRAFORM_USER_DATA_PATH" \
                  '{
                  run_id: $run_id,
                  region: $region,
                  creation_time: $creation_time,
                  k8s_machine_type: $k8s_machine_type,
                  user_data_path: $user_data_path
                  }' | jq 'with_entries(select(.value != null and .value != ""))')
          fi
          input_variables_str=$(echo $INPUT_VARIABLES | jq -c .)
          echo "Input variables: $input_variables_str"
          regional_config=$(echo "$regional_config" | jq --arg region "$REGION" --arg input_variable "$input_variables_str" \
            '.[$region].TERRAFORM_INPUT_VARIABLES += $input_variable')
          echo "Regional config: $regional_config"
          INPUT_VARIABLES=""
        done
        regional_config_str=$(echo $regional_config | jq -c .)
        echo "Final regional config: $regional_config_str"
        echo "##vso[task.setvariable variable=TERRAFORM_REGIONAL_CONFIG]$regional_config_str"
    """
    ).strip(),
    env={
        "CLOUD": cloud,
        "REGIONS": regions,
        "RUN_ID": "$(RUN_ID)",
        "INPUT_VARIABLES": input_variables,
        "DEBUG": "$(System.Debug)",
    },
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
)

set_input_variables_azure = lambda cloud, regions, input_variables={}: Script(
    display_name="Set Terraform Input Variables",
    script=dedent(
        """
        set -e

        if [[ "${DEBUG,,}" =~ "true" ]]; then
          set -x
        fi

        SYSTEM_NODE_POOL=${SYSTEM_NODE_POOL:-null}
        USER_NODE_POOL=${USER_NODE_POOL:-null}

        if [ -z "$(AKS_CLI_CUSTOM_HEADERS)" ]; then
          AKS_CUSTOM_HEADERS='[]'
        else
          IFS=', ' read -r -a aks_custom_headers_array <<< "$(AKS_CLI_CUSTOM_HEADERS)"
          AKS_CUSTOM_HEADERS=$(printf '%s\n' "${aks_custom_headers_array[@]}" | jq -R . | jq -s .)
        fi

        regional_config=$REGIONAL_CONFIG
        for REGION in $(echo "$REGIONS" | jq -r '.[]'); do
          if [ -z "$INPUT_VARIABLES" ]; then
            echo "Set input variables for region $REGION"
            INPUT_VARIABLES=$(jq -n \
                  --arg run_id $RUN_ID \
                  --arg region $REGION \
                  --arg aks_sku_tier "$SKU_TIER" \
                  --arg aks_kubernetes_version "$KUBERNETES_VERSION" \
                  --arg aks_network_policy "$NETWORK_POLICY" \
                  --arg aks_network_dataplane "$NETWORK_DATAPLANE" \
                  --arg k8s_machine_type "$K8S_MACHINE_TYPE" \
                  --arg k8s_os_disk_type "$K8S_OS_DISK_TYPE" \
                  --argjson aks_custom_headers "$AKS_CUSTOM_HEADERS" \
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
                    aks_custom_headers: $aks_custom_headers,
                    aks_cli_system_node_pool: $aks_cli_system_node_pool,
                    aks_cli_user_node_pool: $aks_cli_user_node_pool
                  }' | jq 'with_entries(select(.value != null and .value != ""))')
          fi
          input_variables_str=$(echo $INPUT_VARIABLES | jq -c .)
          echo "Input variables: $input_variables_str"
          regional_config=$(echo "$regional_config" | jq --arg region "$REGION" --arg input_variable "$input_variables_str" \
              '.[$region].TERRAFORM_INPUT_VARIABLES += $input_variable')
          echo "Regional config: $regional_config"
          INPUT_VARIABLES=""
        done
        regional_config_str=$(echo $regional_config | jq -c .)
        echo "Final regional config: $regional_config_str"
        echo "##vso[task.setvariable variable=TERRAFORM_REGIONAL_CONFIG]$regional_config_str"
    """
    ).strip(),
    env={
        "CLOUD": cloud,
        "REGIONS": regions,
        "RUN_ID": "$(RUN_ID)",
        "INPUT_VARIABLES": input_variables,
        "DEBUG": "$(System.Debug)",
        "SKU_TIER": "$(SKU_TIER)",
        "KUBERNETES_VERSION": "$(KUBERNETES_VERSION)",
        "NETWORK_POLICY": "$(NETWORK_POLICY)",
        "NETWORK_DATAPLANE": "$(NETWORK_DATAPLANE)",
        "K8S_MACHINE_TYPE": "$(K8S_MACHINE_TYPE)",
        "K8S_OS_DISK_TYPE": "$(K8S_OS_DISK_TYPE)",
        "AKS_CLI_CUSTOM_HEADERS": "$(AKS_CLI_CUSTOM_HEADERS)",
        "SYSTEM_NODE_POOL": "$(SYSTEM_NODE_POOL)",
        "USER_NODE_POOL": "$(USER_NODE_POOL)",
    },
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
)
set_input_variables_gcp = lambda cloud, regions, input_variables={}: Script(
    display_name="Set Terraform Input Variables",
    script=dedent(
        """
        set -e

        CREATION_TIME=$(date -uIseconds | sed 's/+00:00/Z/')
        regional_config=$REGIONAL_CONFIG
        for REGION in $(echo "$REGIONS" | jq -r '.[]'); do
          if [ -z "$INPUT_VARIABLES" ]; then
            echo "Set input variables for region $REGION"
            INPUT_VARIABLES=$(jq -n \
              --arg project_id "$PROJECT_ID" \
              --arg run_id "$RUN_ID" \
              --arg region "$REGION" \
              --arg creation_time "$CREATION_TIME" \
              '{
                project_id: $project_id,
                run_id: $run_id,
                region: $region,
                creation_time: $creation_time
              }' | jq 'with_entries(select(.value != null and .value != ""))')
          fi
          input_variables_str=$(echo $INPUT_VARIABLES | jq -c .)
          echo "Input variables: $input_variables_str"
          regional_config=$(echo "$regional_config" | jq --arg region "$REGION" --arg input_variable "$input_variables_str" \
              '.[$region].TERRAFORM_INPUT_VARIABLES += $input_variable')
          echo "Regional config: $regional_config"
          INPUT_VARIABLES=""
        done
        regional_config_str=$(echo $regional_config | jq -c .)
        echo "Final regional config: $regional_config_str"
        echo "##vso[task.setvariable variable=TERRAFORM_REGIONAL_CONFIG]$regional_config_str"
    """
    ).strip(),
    env={
        "CLOUD": cloud,
        "REGIONS": regions,
        "RUN_ID": "$(RUN_ID)",
        "INPUT_VARIABLES": input_variables,
        "DEBUG": "$(System.Debug)",
        "PROJECT_ID": "$(GCP_PROJECT_ID)",
    },
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
)

set_input_variables = lambda cloud, regions, input_variables={}, project_id="": {
    "aws": lambda: set_input_variables_aws(cloud, regions, input_variables),
    "azure": lambda: set_input_variables_azure(cloud, regions, input_variables),
    "gcp": lambda: set_input_variables_gcp(cloud, regions, input_variables, project_id),
}.get(cloud, lambda: ValueError(f"Unsupported cloud type: {cloud}"))()
