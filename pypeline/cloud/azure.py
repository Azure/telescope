import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent

from benchmark import Cloud
from pipeline import Script, Step, Task


class CredentialType(Enum):
    MANAGED_IDENTITY = "managed_identity"
    SERVICE_CONNECTION = "service_connection"


@dataclass
class Azure(Cloud):
    region: str = "eastus"
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
                        """
                        set -eu
                        echo "login to Azure in $REGION"
                        az login --identity --username $AZURE_MI_ID
                        az account set --subscription "$AZURE_MI_SUBSCRIPTION_ID"
                        az config set defaults.location="$REGION"
                        az account show
                        """.strip(
                            "\n"
                        )
                    ),
                    env={
                        "AZURE_MI_ID": self.azure_mi_client_id,
                        "AZURE_MI_SUBSCRIPTION_ID": self.subscription,
                        "REGION": self.region,
                    },
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
                            """.strip(
                                "\n"
                            )
                        ),
                        "addSpnToEnvironment": "true",
                    },
                ),
                Script(
                    display_name="Azure Login",
                    script=dedent(
                        """
                        set -eu

                        echo "login to Azure in $REGION"
                        az login --service-principal --tenant $(TENANT_ID) -u $(SP_CLIENT_ID) --federated-token $(SP_ID_TOKEN) --allow-no-subscriptions
                        az account set --subscription "$AZURE_SP_SUBSCRIPTION_ID"
                        az config set defaults.location="$REGION"
                        az account show
                        """.strip(
                            "\n"
                        )
                    ),
                    env={
                        "REGION": self.region,
                        "AZURE_SP_SUBSCRIPTION_ID": self.subscription,
                    },
                ),
            ]
