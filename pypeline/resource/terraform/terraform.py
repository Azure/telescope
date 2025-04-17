from textwrap import dedent

from benchmark import Resource, Cloud
from pipeline import Script, Step
from resource.terraform.input_variables import set_input_variables
from resource.terraform.run_command import run_command
import os

set_working_directory = lambda cloud, modules_dir: Script(
    display_name="Set Terraform  Working Directory",
    script=dedent(
        """
        if [ -n "$MODULES_DIR" ]; then
            terraform_working_directory=$(Pipeline.Workspace)/s/$MODULES_DIR
        else
            terraform_working_directory=$(Pipeline.Workspace)/s/modules/terraform/$CLOUD
        fi
        echo "##vso[task.setvariable variable=TERRAFORM_WORKING_DIRECTORY]$terraform_working_directory"
        echo "Terraform Working Directory: $terraform_working_directory
        """.strip(
            "\n"
        )
    ),
    env={"CLOUD": cloud, "MODULES_DIR": modules_dir},
)

set_input_file = lambda cloud, regions, input_file_mapping: Script(
    display_name="Set Terraform Input File",
    script=dedent(
        """
        set -eu

        regional_config=$(jq -n '{}')

        terraform_file_config=$(echo "${{ convertToJson(parameters.input_file_mapping) }}" | \
            sed -E 's/([a-zA-Z0-9_-]+):/"\\1":/g; s/: ([^",]+)/: "\\1"/g' | jq -r '.[]')

        multi_region=$(echo "$REGIONS" | jq -r 'if length > 1 then "true" else "false" end')
        echo "##vso[task.setvariable variable=MULTI_REGION]$multi_region"

        for region in $(echo "$REGIONS" | jq -r '.[]'); do
            if [ -n "$terraform_file_config" ]; then
                # Use the regional input file path from the mapping
                regional_input_file_path=$(echo "$terraform_file_config" | jq -r --arg region "$region" '.[$region]')
                terraform_input_file=$(Pipeline.Workspace)/s/${regional_input_file_path}
            elif [ "$multi_region" = "false" ]; then
                # Use the default input file for single-region deployments
                terraform_input_file=$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}.tfvars
            else
                # Use the region-specific input file for multi-region deployments
                terraform_input_file=$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/terraform-inputs/${CLOUD}-${region}.tfvars
            fi

            # Add the file path to the regional configuration
            regional_config=$(echo $regional_config | jq --arg region $region --arg file_path $terraform_input_file \
                '. + {($region): {"TERRAFORM_INPUT_FILE" : $file_path}}')
        done

        regional_config_str=$(echo $regional_config | jq -c .)
        echo "##vso[task.setvariable variable=REGIONAL_CONFIG]$regional_config_str"
        """
    ).strip(),
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    env={
        "CLOUD": cloud,
        "REGIONS": regions,
    },
)


set_user_data_path = lambda user_data_path: Script(
    display_name="Set User Data Path",
    script=dedent(
        """
        if [ -v "$USER_DATA_PATH" ]; then
            terraform_user_data_path=$(Pipeline.Workspace)/s/$USER_DATA_PATH
        else
            terraform_user_data_path=$(Pipeline.Workspace)/s/scenarios/$SCENARIO_TYPE/$SCENARIO_NAME/scripts/user_data
        fi
        echo $terraform_user_data_path
        echo "##vso[task.setvariable variable=TERRAFORM_USER_DATA_PATH]$terraform_user_data_path"
        """.strip(
            "\n"
        )
    ),
    env={"USER_DATA_PATH": user_data_path},
)

get_deletion_info = lambda region: Script(
    display_name="Get Deletion Due Time and Owner",
    script=dedent(
        """
        set -e

        terraform_input_file=$(echo $TERRAFORM_REGIONAL_CONFIG | jq -r --arg region "$region" '.[$region].TERRAFORM_INPUT_FILE')

        deletion_delay=$(grep 'deletion_delay' "$terraform_input_file" | awk -F'=' '{gsub(/^[ \\t]+|[ \\t]+$/, "", $2); gsub(/[^0-9]/, "", $2); print $2}')
        echo "Deletion Delay: $deletion_delay hr"

        deletion_due_time=$(date -u -d "+${deletion_delay} hour" +'%Y-%m-%dT%H:%M:%SZ')
        echo "Deletion Due Time: $deletion_due_time"
        echo "##vso[task.setvariable variable=DELETION_DUE_TIME]$deletion_due_time"

        owner=$(grep 'owner' "$terraform_input_file" | awk -F'=' '{gsub(/^[ \\t]+|[ \\t]+$/, "", $2); print $2}' | sed 's/^"//;s/"$//')
        echo "Owner: $owner"
        echo "##vso[task.setvariable variable=OWNER]$owner"
        """
    ).strip(),
    condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    env={"region": region},
)

create_resource_group = lambda cloud, regions: Script(
    display_name="Create Resource Group",
    script=dedent(
        """
        set -eu
        echo "Create resource group $RUN_ID in region $region"
        az group create --name $RUN_ID --location $region \
          --tags "run_id=$RUN_ID" "scenario=${SCENARIO_TYPE}-${SCENARIO_NAME}" "owner=${OWNER}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=${DELETION_DUE_TIME}" "SkipAKSCluster=1"
        """.strip(
            "\n"
        )
    ),
    condition=f"and(eq('{cloud}', 'azure'), ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true'))",
    env={"region": regions},
)


class Terraform(Resource):
    cloud_obj : Cloud = None
    cloud: str = ''
    regions: str = ''
    credential_type: str = ''
    modules_dir: str = "" 
    input_file_mapping: [] = []
    user_data_path: str = ""
    input_variables: dict[str, str] = {}
    retry_attempt_count: int = 3
    arguments: str = ""
    
    def __init__( self, cloud_obj: Cloud, modules_dir='', input_file_mapping=[], user_data_path="", input_variables={}, retry_attempt_count=3, arguments=""):
        self.cloud = cloud_obj.get_cloud_type()
        self.regions = cloud_obj.get_region()
        self.credential_type = cloud_obj.get_credential_type()
        self.modules_dir = modules_dir
        self.input_file_mapping = input_file_mapping
        self.user_data_path = user_data_path
        self.input_variables = input_variables
        self.retry_attempt_count = retry_attempt_count
        self.arguments = arguments
    
    

    def setup(self) -> list[Step]:
        return [
            set_working_directory(self.cloud, self.modules_dir),
            set_input_file(self.cloud, self.regions, self.input_file_mapping),
            set_user_data_path(self.user_data_path),
            set_input_variables(self.cloud, self.regions, self.input_variables),
            get_deletion_info(self.regions),
            create_resource_group(self.cloud, self.regions),
            run_command(
                command="version", 
                credential_type=self.credential_type),
            run_command(
                command="init", 
                retry_attempt_count=self.retry_attempt_count, 
                credential_type=self.credential_type),
            run_command(
                command="apply",
                arguments=self.arguments,
                regions=self.regions,
                cloud=self.cloud,
                retry_attempt_count=self.retry_attempt_count,
                credential_type=self.credential_type,
            ),
        ]

    def validate(self) -> list[Step]:
        return []

    def tear_down(self) -> list[Step]:
        return []
