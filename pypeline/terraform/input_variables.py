import json
from datetime import datetime
from textwrap import dedent

from pipeline import Script


def set_input_variables(
    cloud: str, regions: list[str], input_variables: dict
) -> Script:
    # Initialize regional configuration
    regional_config = {}

    # Generate input variables for each region
    for region in regions:
        region_input_variables = generate_input_variables(
            cloud, region, input_variables
        )
        regional_config[region] = {"TERRAFORM_INPUT_VARIABLES": region_input_variables}

    # Convert regional configuration to JSON
    regional_config_str = json.dumps(regional_config)

    # Generate the script to set pipeline variables
    return Script(
        display_name="Set Terraform Input Variables",
        script=dedent(
            f"""
            set -e
            if [[ \"${{DEBUG,,}}\" =~ \"true\" ]]; then
                set -x
            fi
            echo "##vso[task.setvariable variable=TERRAFORM_REGIONAL_CONFIG]{regional_config_str}"
            echo "Regional configuration set successfully."
            """
        ).strip(),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


def generate_input_variables(cloud: str, region: str, input_variables: dict) -> dict:
    # Generate creation time in ISO 8601 format with Zulu time
    creation_time = datetime.utcnow().isoformat() + "Z"

    if cloud == "aws":
        return {
            "run_id": "$(RUN_ID)",
            "region": region,
            "creation_time": creation_time,
            "k8s_machine_type": input_variables.get(
                "k8s_machine_type", "$K8S_MACHINE_TYPE"
            ),
            "user_data_path": input_variables.get(
                "user_data_path", "$TERRAFORM_USER_DATA_PATH"
            ),
        }
    elif cloud == "azure":
        aks_custom_headers_env = input_variables.get(
            "aks_custom_headers", "$AKS_CLI_CUSTOM_HEADERS"
        )
        aks_custom_headers = []
        if aks_custom_headers_env:
            aks_custom_headers = [
                header.strip()
                for header in aks_custom_headers_env.split(",")
                if header.strip()
            ]

        return {
            "run_id": "$(RUN_ID)",
            "region": region,
            "aks_sku_tier": input_variables.get("sku_tier", "$AKS_SKU_TIER"),
            "aks_kubernetes_version": input_variables.get(
                "kubernetes_version", "$KUBERNETES_VERSION"
            ),
            "aks_network_policy": input_variables.get(
                "network_policy", "$NETWORK_POLICY"
            ),
            "aks_network_dataplane": input_variables.get(
                "network_dataplane", "$NETWORK_DATAPLANE"
            ),
            "k8s_machine_type": input_variables.get(
                "k8s_machine_type", "$K8S_MACHINE_TYPE"
            ),
            "k8s_os_disk_type": input_variables.get(
                "k8s_os_disk_type", "$K8S_OS_DISK_TYPE"
            ),
            "aks_custom_headers": aks_custom_headers,
            "aks_cli_system_node_pool": input_variables.get(
                "system_node_pool", "$SYSTEM_NODE_POOL"
            ),
            "aks_cli_user_node_pool": input_variables.get(
                "user_node_pool", "$USER_NODE_POOL"
            ),
        }
    elif cloud == "gcp":
        return {
            "project_id": input_variables.get("project_id", "$GCP_PROJECT_ID"),
            "run_id": "$(RUN_ID)",
            "region": region,
            "creation_time": creation_time,
        }
    else:
        raise ValueError(f"Unsupported cloud type: {cloud}")
