import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent

from benchmark import Cloud, CloudProvider
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

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

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

    def generate_input_variables(self, region: str, input_variables: dict) -> dict:
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

    def create_resource_group(self, region: str) -> Script:
        return Script(
            display_name="Create Resource Group",
            script=dedent(
                f"""
                set -eu
                echo "Create resource group $RUN_ID in region {region}"
                az group create --name $RUN_ID --location {region} \\
                --tags "run_id=$RUN_ID" "scenario=${{SCENARIO_TYPE}}-${{SCENARIO_NAME}}" "owner=${{OWNER}}" "creation_date=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "deletion_due_time=${{DELETION_DUE_TIME}}" "SkipAKSCluster=1"
                """
            ).strip(),
            condition="ne(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
        )

    def delete_resource_group(self) -> str:
        return dedent(
            """
            echo "Deleting resources and removing state file before retrying"
            ids=$(az resource list --location $region --resource-group $RUN_ID --query [*].id -o tsv)
            az resource delete --ids $ids --verbose
            rm -r terraform.tfstate.d/$region
            """
        ).strip("")
