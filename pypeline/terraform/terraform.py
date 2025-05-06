import json
import os
from dataclasses import dataclass, field
from textwrap import dedent
from typing import List

from components import CredentialType
from pipeline import Script, Step
from terraform.input_variables import set_input_variables
from terraform.run_command import (generate_apply_or_destroy_script,
                                   generate_generic_script)


def generate_regional_config(
    cloud: str, regions: str, input_file_mapping: dict
) -> dict:
    regional_config = {}
    multi_region = len(regions) > 1

    for region in regions:
        if input_file_mapping and region in input_file_mapping:
            regional_input_file_path = input_file_mapping[region]
            terraform_input_file = f"$(Pipeline.Workspace)/s/{regional_input_file_path}"
        elif not multi_region:
            terraform_input_file = f"$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/{cloud}.tfvars"
        else:
            terraform_input_file = f"$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/{cloud}-{region}.tfvars"

        regional_config[region] = {"TERRAFORM_INPUT_FILE": terraform_input_file}

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


def set_input_file(cloud: str, regions: str, input_file_mapping: dict) -> Script:
    config = generate_regional_config(cloud, regions, input_file_mapping)
    regional_config = config["regional_config"]
    multi_region = config["multi_region"]

    regional_config_str = json.dumps(regional_config)

    return Script(
        display_name="Set Terraform Input File",
        script=dedent(
            f"""
            set -eu

            echo "##vso[task.setvariable variable=MULTI_REGION]{str(multi_region).lower()}"
            echo "##vso[task.setvariable variable=REGIONAL_CONFIG]{regional_config_str}"
            """
        ).strip(),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


def set_user_data_path(user_data_path: str) -> Script:
    if user_data_path:
        terraform_user_data_path = f"$(Pipeline.Workspace)/s/{user_data_path}"
    else:
        terraform_user_data_path = "$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/scripts/user_data"

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


def get_deletion_info(region: str) -> Script:
    return Script(
        display_name="Get Deletion Due Time and Owner",
        script=dedent(
            f"""
            set -e

            terraform_input_file=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "{region}" '.[$region].TERRAFORM_INPUT_FILE')

            deletion_delay=$(grep 'deletion_delay' "$terraform_input_file" | awk -F'=' '{{gsub(/^[ \\t]+|[ \\t]+$/, "", $2); gsub(/[^0-9]/, "", $2); print $2}}')
            echo "Deletion Delay: $deletion_delay hr"

            deletion_due_time=$(date -u -d "+${{deletion_delay}} hour" +'%Y-%m-%dT%H:%M:%SZ')
            echo "Deletion Due Time: $deletion_due_time"
            echo "##vso[task.setvariable variable=DELETION_DUE_TIME]$deletion_due_time"

            owner=$(grep 'owner' "$terraform_input_file" | awk -F'=' '{{gsub(/^[ \\t]+|[ \\t]+$/, "", $2); print $2}}' | sed 's/^"//;s/"$//')
            echo "Owner: $owner"
            echo "##vso[task.setvariable variable=OWNER]$owner"
            """
        ).strip(),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


@dataclass
class Terraform:
    cloud: str
    regions: list[str]
    credential_type: str
    modules_dir: str = ""
    input_file_mapping: List = field(default_factory=list)
    user_data_path: str = ""
    input_variables: dict[str, str] = field(default_factory=dict)
    retry_attempt_count: int = 3
    arguments: str = ""

    def setup(self) -> list[Step]:
        return [
            set_working_directory(self.cloud, self.modules_dir),
            set_input_file(self.cloud, self.regions, self.input_file_mapping),
            set_user_data_path(self.user_data_path),
            set_input_variables(self.cloud, self.regions, self.input_variables),
            get_deletion_info(self.regions[0]),
        ]

    def create_resource_group(self) -> Script:
        return Script(
            display_name="Create Resource Group",
            script=dedent(
                f"""
                set -eu
                echo "Create resource group $RUN_ID in region {self.regions[0]}"
                az group create --name $RUN_ID --location {self.regions[0]} \
                --tags "run_id=$RUN_ID" "scenario=${{SCENARIO_TYPE}}-${{SCENARIO_NAME}}" "owner=${{OWNER}}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=${{DELETION_DUE_TIME}}" "SkipAKSCluster=1"
                """
            ).strip(),
            condition=f"and(eq('{self.cloud}', 'azure'), ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true'))",
        )

    def run_command(self, command: str) -> Script:
        if command == "apply" or command == "destroy":
            script = generate_apply_or_destroy_script(
                command, self.arguments, self.regions, self.cloud
            )
        else:
            script = generate_generic_script(command, self.arguments)

        return Script(
            display_name=f"Run Terraform {command.capitalize()} Command",
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
