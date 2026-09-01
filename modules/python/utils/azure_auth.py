"""Azure credential configuration."""

import os
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential


def configure_credential(
    use_managed_identity=False,
    default_credential_exclude_mi=False,
):
    """Create the Azure credential requested by the caller."""
    if use_managed_identity:
        managed_identity_client_id = os.getenv("AZURE_MI_ID")
        if managed_identity_client_id:
            return ManagedIdentityCredential(client_id=managed_identity_client_id)
        return ManagedIdentityCredential()

    if default_credential_exclude_mi:
        return DefaultAzureCredential(
            exclude_managed_identity_credential=True
        )
    return DefaultAzureCredential()