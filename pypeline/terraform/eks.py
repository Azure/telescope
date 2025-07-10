from dataclasses import dataclass
from textwrap import dedent

from terraform.terraform import Terraform


@dataclass
class EKS(Terraform):
    def delete_resources(self) -> str:
        # TO DO: replace with actual EKS deletion commands
        return dedent(
            """
            echo "Deleting EKS resources"
            """
        ).strip()
