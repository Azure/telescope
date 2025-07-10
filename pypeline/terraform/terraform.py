import json
import os
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from textwrap import dedent, indent
from typing import List

from benchmark import Cloud, Resource
from cloud.azure import CredentialType
from pipeline import Script, Step


class TerraformCommand(Enum):
    INIT = "init"
    VERSION = "version"
    APPLY = "apply"
    DESTROY = "destroy"


def generate_regional_config(
    cloud: str, regions: str, input_file_mapping: dict,
    scenario_name: str, scenario_type: str
) -> dict:
    regional_config = {}
    multi_region = len(regions) > 1

    for region in regions:
        if input_file_mapping and region in input_file_mapping:
            regional_input_file_path = input_file_mapping[region]
            terraform_input_file = f"$(Pipeline.Workspace)/s/{regional_input_file_path}"
        elif not multi_region:
            terraform_input_file = f"$(Pipeline.Workspace)/s/scenarios/{scenario_type}/{scenario_name}/terraform-inputs/{cloud.provider.value}.tfvars"
        else:
            terraform_input_file = f"$(Pipeline.Workspace)/s/scenarios/{scenario_type}/{scenario_name}/terraform-inputs/{cloud.provider.value}-{region}.tfvars"

        regional_config[f"\"{region}\""] = {"\"TERRAFORM_INPUT_FILE\"": f"\"{terraform_input_file}\""}

    return {
        "regional_config": regional_config,
        "multi_region": multi_region,
    }


def set_working_directory(cloud: str, modules_dir: str) -> Script:
    if modules_dir and os.path.exists(
        os.path.join(os.getenv("Pipeline.Workspace", ""), "s", modules_dir)
    ):
        terraform_working_directory = f"$(Pipeline.Workspace)/s/{modules_dir}"
    else:
        terraform_working_directory = (
            f"$(Pipeline.Workspace)/s/modules/terraform/{cloud}"
        )

    return Script(
        display_name="Set Terraform Working Directory",
        script=dedent(
            f"""
            echo "##vso[task.setvariable variable=TERRAFORM_WORKING_DIRECTORY]{terraform_working_directory}"
            echo "Terraform Working Directory: {terraform_working_directory}"
            """
        ).strip(),
    )


def set_user_data_path(
    user_data_path: str, scenario_name: str, scenario_type: str
) -> Script:
    if user_data_path:
        terraform_user_data_path = f"$(Pipeline.Workspace)/s/{user_data_path}"
    else:
        terraform_user_data_path = f"$(Pipeline.Workspace)/s/scenarios/{scenario_type}/{scenario_name}/scripts/user_data"

    return Script(
        display_name="Set User Data Path",
        script=dedent(
            f"""
            echo {terraform_user_data_path}
            
            if [ -d "{terraform_user_data_path}" ]; then
                echo "Terraform user data path exists: {terraform_user_data_path}"
                echo "##vso[task.setvariable variable=TERRAFORM_USER_DATA_PATH]{terraform_user_data_path}"
            else:
                echo "Terraform user data path does not exist: {terraform_user_data_path}"
            fi
            """
        ).strip(),
    )


def set_input(
    cloud: Cloud,
    regions: list[str],
    input_variables: dict,
    input_file_mapping: dict,
    scenario_name: str,
    scenario_type: str,
) -> Script:
    # Initialize regional configuration
    regional_config = {}

    config = generate_regional_config(
        cloud, regions, input_file_mapping, scenario_name, scenario_type
    )
    regional_config = config["regional_config"]
    multi_region = config["multi_region"]

    # Generate input variables for each region
    for region in regions:
        region_input_variables = cloud.generate_input_variables(region, input_variables)
        regional_config[f'"{region}"']['"TERRAFORM_INPUT_VARIABLES"'] = f"\"{json.dumps(region_input_variables)}\""

    # Convert regional configuration to JSON
    regional_config_str = json.dumps(regional_config)

    # Generate the script to set pipeline variables
    return Script(
        display_name="Set Terraform Input Variables and Input File",
        script=dedent(
            f"""
            set -e
            if [[ \"${{DEBUG,,}}\" =~ \"true\" ]]; then
                set -x
            fi
            echo "Regional Configuration {regional_config_str}"
            echo "##vso[task.setvariable variable=MULTI_REGION]{str(multi_region).lower()}"
            regional_config_str=$(echo "{regional_config_str}" | jq -c .)
            echo "Final regional config: $regional_config_str"
            echo "##vso[task.setvariable variable=TERRAFORM_REGIONAL_CONFIG]$regional_config_str"
            
            echo "Regional configuration set successfully."
            """
        ).strip(),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


def generate_workspace_script() -> str:
    return dedent(
        """
        if terraform workspace list | grep -q "$region"; then
            terraform workspace select $region
        else:
            terraform workspace new $region
            terraform workspace select $region
        fi
        """
    ).strip("")


def generate_generic_script(command: str, arguments: str) -> str:
    return dedent(
        f"""
        set -e
        
        # Navigate to the Terraform working directory
        cd $TERRAFORM_WORKING_DIRECTORY

        # Run Terraform {command} command
        terraform {command} {arguments}
        """
    ).strip()


def generate_apply_or_destroy_script(
    command: TerraformCommand,
    arguments: str,
    regions: list[str],
    error_handling_script: str,
) -> str:
    workspace_script = indent(generate_workspace_script(), " " * 12)

    return dedent(
        f"""
        set -e
        echo "Regional Config: $TERRAFORM_REGIONAL_CONFIG"

        # Navigate to the Terraform working directory
        cd $TERRAFORM_WORKING_DIRECTORY

        for region in $(echo '{regions}' | jq -r '.[]'); do
            echo "Processing region: $region"
            {workspace_script}
            # Retrieve input file and variables
            terraform_input_file=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')
            terraform_input_variables=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_VARIABLES')

            # Run Terraform {command.value} command
            set +e
            terraform {command.value} --auto-approve {arguments} -var-file $terraform_input_file -var json_input="$terraform_input_variables"
            exit_code=$?
            set -e

            # Handle errors
            if [[ $exit_code -ne 0 ]]; then
                echo "Terraform {command.value} failed for region: $region"
                {error_handling_script}
                exit 1
            fi
          
        done
        """
    ).strip()


# TODO: Add delete_resource_group function and validate_resource_group function
@dataclass
class Terraform(Resource):
    cloud: Cloud
    regions: list[str]
    scenario_name: str
    scenario_type: str = "perf-eval"
    credential_type: CredentialType = CredentialType.SERVICE_CONNECTION
    modules_dir: str = ""
    input_file_mapping: List = field(default_factory=list)
    user_data_path: str = ""
    input_variables: dict[str, str] = field(default_factory=dict)
    retry_attempt_count: int = 3
    arguments: str = ""

    def setup(self) -> list[Step]:

        return [
            set_working_directory(self.cloud.provider.value, self.modules_dir),
            set_user_data_path(
                self.user_data_path, self.scenario_name, self.scenario_type
            ),
            set_input(
                self.cloud,
                self.regions,
                self.input_variables,
                self.input_file_mapping,
                self.scenario_name,
                self.scenario_type,
            ),
            self.run_command(TerraformCommand.VERSION),
            self.run_command(TerraformCommand.INIT),
            self.run_command(TerraformCommand.APPLY),
        ]

    def validate(self):
        return []

    def tear_down(self):
        return []

    def run_command(
        self,
        command: TerraformCommand,
    ) -> Script:
        if command == TerraformCommand.APPLY or TerraformCommand.DESTROY:
            script = self.generate_terraform_command_script(command)
        else:
            script = generate_generic_script(command, self.arguments)

        return Script(
            display_name=f"Run Terraform {command.value.capitalize()} Command",
            script=script,
            condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
            retry_count_on_task_failure=self.retry_attempt_count,
            env={
                "ARM_SUBSCRIPTION_ID": "$(AZURE_SUBSCRIPTION_ID)",
                **(
                    {
                        "ARM_USE_MSI": "true",
                        "ARM_TENANT_ID": "$(AZURE_MI_TENANT_ID)",
                        "ARM_CLIENT_ID": "$(AZURE_MI_CLIENT_ID)",
                    }
                    if self.credential_type == CredentialType.MANAGED_IDENTITY
                    else {}
                ),
            },
        )

    @abstractmethod
    def generate_terraform_command_script(self, command) -> str:
        pass
