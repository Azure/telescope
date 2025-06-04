from dataclasses import dataclass
from textwrap import dedent

from benchmark import CloudProvider, Resource
from pipeline import Script


def create_resource_group(
    region: str, scenario_name: str, scenario_type: str, owner: str
) -> Script:
    return Script(
        display_name="Create Resource Group",
        script=dedent(
            f"""
            set -eu
            echo "Create resource group $RUN_ID in region {region}"
            az group create --name $RUN_ID --location {region} \\
            --tags "run_id=$RUN_ID" "scenario={scenario_type}-{scenario_name}" "owner={owner}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=${{DELETION_DUE_TIME}}" "SkipAKSCluster=1"
            """
        ).strip(),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


def delete_resource_group(region: str) -> Script:
    return Script(
        display_name="Delete Resource Group",
        script=dedent(
            f"""
            echo "Deleting resources and removing state file before retrying"
            ids=$(az resource list --location {region} --resource-group $RUN_ID --query [*].id -o tsv)
            az resource delete --ids $ids --verbose
            rm -r terraform.tfstate.d/{region}
            """
        ).strip(""),
        condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


# This is for handling cloud resources at terraform
@dataclass
class ResourceGroup(Resource):
    region: str
    scenario_name: str
    scenario_type: str = "perf-eval"
    owner: str = "aks"

    def setup(self) -> list[Script]:
        return [
            create_resource_group(
                self.region, self.scenario_name, self.scenario_type, self.owner
            )
        ]

    def validate(self) -> list[Script]:
        return []

    def tear_down(self) -> list[Script]:
        return [delete_resource_group(self.region)]
