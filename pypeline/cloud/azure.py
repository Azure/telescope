import os
from dataclasses import dataclass, field
from enum import Enum
from textwrap import dedent

from benchmark import Cloud
from pipeline import Script, Step, Task


class CredentialType(Enum):
    MANAGED_IDENTITY = "managed_identity"
    SERVICE_CONNECTION = "service_connection"


@dataclass
class Azure(Cloud):
    regions: list[str] = field(default_factory=lambda: ["eastus2"])
    subscription: str = os.getenv("AZURE_SUBSCRIPTION_ID")
    credential_type: CredentialType = CredentialType.SERVICE_CONNECTION
    azure_service_connection: str = os.getenv("AZURE_SERVICE_CONNECTION")
    azure_mi_client_id: str = os.getenv("AZURE_MI_CLIENT_ID")

    def login(self) -> list[Step]:
        if self.credential_type == CredentialType.MANAGED_IDENTITY:
            return [
                Script(
                    display_name="Azure Login",
                    script=dedent(
                        f"""
                        set -eu
                        echo "login to Azure in {self.regions[0]}"
                        az login --identity --username {self.azure_mi_id}
                        az account set --subscription "{self.azure_subscription_id}"
                        az config set defaults.location="{self.regions[0]}"
                        az account show
                        """
                    ),
                ),
            ]
        elif self.credential_type == CredentialType.SERVICE_CONNECTION:
            return [
                Task(
                    display_name="Get login credentials",
                    task="AzureCLI@2",
                    inputs={
                        "azureSubscription": self.azure_service_connection,
                        "scriptType": "bash",
                        "scriptLocation": "inlineScript",
                        "inlineScript": dedent(
                            """
                            echo "##vso[task.setvariable variable=SP_CLIENT_ID;issecret=true]$servicePrincipalId"
                            echo "##vso[task.setvariable variable=SP_ID_TOKEN;issecret=true]$idToken"
                            echo "##vso[task.setvariable variable=TENANT_ID;issecret=true]$tenantId"
                            """
                        ),
                        "addSpnToEnvironment": "true",
                    },
                ),
                Script(
                    display_name="Azure Login",
                    script=dedent(
                        f"""
                        set -eu

                        echo "login to Azure in {self.regions[0]}"
                        az login --service-principal --tenant $(TENANT_ID) -u $(SP_CLIENT_ID) --federated-token $(SP_ID_TOKEN) --allow-no-subscriptions
                        az account set --subscription "{self.subscription}"
                        az config set defaults.location="{self.regions[0]}"
                        az account show
                        """
                    ),
                ),
            ]

    # TODO: Add collect cloud info, update kubeconfig, and upload storage-account
