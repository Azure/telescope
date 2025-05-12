from dataclasses import dataclass
from textwrap import dedent

from benchmark import Resource
from pipeline import Script, Step


def generate_ssh_key(cloud: str) -> Script:
    return Script(
        display_name="Generate SSH Key",
        script=dedent(
            f"""
            set -eu

            ssh_key_path="$(Pipeline.Workspace)/s/modules/terraform/{cloud}/private_key.pem"
            public_key_path="$(Pipeline.Workspace)/s/modules/terraform/{cloud}/private_key.pem.pub"
            ssh-keygen -t rsa -b 2048 -f $ssh_key_path -N "" > /dev/null 2>&1
            chmod 600 $ssh_key_path

            echo "SSH Key Path: $ssh_key_path"
            echo "##vso[task.setvariable variable=SSH_KEY_PATH;]$ssh_key_path"
            echo "Public Key Path: $public_key_path"
            echo "##vso[task.setvariable variable=SSH_PUBLIC_KEY_PATH;]$public_key_path"
            """
        ).strip(),
    )


def download_ssh_key() -> Script:
    return Script(
        display_name="Download SSH Key",
        script=dedent(
            """
            set -eu

            echo "Get private key from key vault $AZURE_SSH_KEY_VAULT"
            az keyvault secret download --id $AZURE_SSH_KEY_VAULT --file $SSH_KEY_PATH
            chmod 600 $SSH_KEY_PATH
            cat $SSH_KEY_PATH
            echo "##vso[task.setvariable variable=SSH_KEY_PATH;]${SSH_KEY_PATH}"
            """
        ).strip(),
        condition="eq(variables['SKIP_RESOURCE_MANAGEMENT'], 'true')",
    )


def validate_ssh_key() -> Script:
    return Script(
        display_name="Validate SSH Key",
        script=dedent(
            """
            set -eu

            # Check if the private key file exists
            if [ ! -f "$SSH_KEY_PATH" ]; then
                echo "Error: SSH private key not found at $SSH_KEY_PATH"
                exit 1
            fi

            # Check if the private key has the correct permissions
            if [ "$(stat -c %a $SSH_KEY_PATH)" != "600" ]; then
                echo "Error: SSH private key permissions are not set to 600"
                exit 1
            fi

            # Check if the public key file exists
            if [ ! -f "$PUBLIC_KEY_PATH" ]; then
                echo "Error: SSH public key not found at $SSH_PUBLIC_KEY_PATH"
                exit 1
            fi

            echo "SSH key validation passed."
            """
        ).strip(),
    )


def remove_ssh_key() -> list[Step]:
    return Script(
        display_name="Delete SSH Keys",
        script=dedent(
            """
            set -eu
            # Check if the private key file exists
            if [ ! -f "$SSH_KEY_PATH" ]; then
                echo "Error: Private SSH key not found at $SSH_KEY_PATH"
                exit 1
            fi
            echo "Deleting private SSH key at $SSH_KEY_PATH"
            rm -f "$SSH_KEY_PATH"

            # Check if the public key file exists
            if [ ! -f "$SSH_PUBLIC_KEY_PATH" ]; then
                echo "Error: Public SSH key not found at $SSH_PUBLIC_KEY_PATH"
                exit 1
            fi
            echo "Deleting public SSH key at $SSH_PUBLIC_KEY_PATH"
            rm -f "$SSH_PUBLIC_KEY_PATH"

            echo "SSH keys deleted successfully."
            """
        ).strip(),
    )


@dataclass
class SSH(Resource):
    cloud: str

    def setup(self) -> list[Step]:
        return [generate_ssh_key(self.cloud), download_ssh_key()]

    def validate(self) -> list[Step]:
        return [validate_ssh_key()]

    def tear_down(self) -> list[Step]:
        return [remove_ssh_key()]
