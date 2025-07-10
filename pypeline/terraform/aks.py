from dataclasses import dataclass
from textwrap import dedent, indent

from terraform.terraform import (Terraform, TerraformCommand,
                                 generate_apply_or_destroy_script)


@dataclass
class AKS(Terraform):
    def delete_resources(self) -> str:
        return dedent(
            f"""
            echo "Deleting resources and removing state file before retrying"
            ids=$(az resource list --location {self.regions[0]} --resource-group $RUN_ID --query [*].id -o tsv)
            az resource delete --ids $ids --verbose
            rm -r terraform.tfstate.d/{self.regions[0]}
            """
        ).strip("")

    def generate_terraform_command_script(self, command) -> str:
        error_handling_script = ""

        if command == TerraformCommand.APPLY:
            error_handling_script = indent(self.delete_resources(), " " * 16)

        return generate_apply_or_destroy_script(
            command=command,
            arguments=self.arguments,
            regions=self.regions,
            error_handling_script=error_handling_script,
        )
