import azure_pipelines.ap.steps

# resolveKeyVaultResourceId returns a script that validates keyId and sets
# KEY_VAULT_RESOURCE_ID to the resource ID of the vault that holds the key.
# keyId must be a versioned key URI, e.g. https://<vault>.vault.azure.net/keys/<key>/<version>.
# It may be a pipeline expression such as "\${{ parameters.kms_key_id }}", so it is validated at runtime.
resolveKeyVaultResourceId = lambda subscription: str, keyId: str -> str {
    """
KEY_ID="${keyId}"
if ! [[ "$KEY_ID" =~ ^https://[^/]+/keys/[^/]+/[^/]+$ ]]; then
  echo "Key ID must be a versioned Key Vault key URI; got '$KEY_ID'."
  exit 1
fi
HOST="\${KEY_ID#https://}"
VAULT_NAME="\${HOST%%.*}"

KEY_VAULT_RESOURCE_ID=$(az keyvault show \\
  --subscription "${subscription}" \\
  --name "$VAULT_NAME" \\
  --query id -o tsv)
"""
}

# GrantKeyVaultCryptoUser grants a managed identity the Key Vault Crypto User role on the vault
# that holds keyId, so AKS can use the key for KMS etcd encryption.
# The role assignment lives on the vault and is not removed when the identity is deleted;
# pair this with RevokeKeyVaultCryptoUser at the end of the pipeline.
GrantKeyVaultCryptoUser = lambda \
    serviceConnection: str, \
    subscription: str, \
    keyId: str, \
    principalId: str, \
    condition: str = Undefined \
    -> steps.Step {
    script = """
${resolveKeyVaultResourceId(subscription, keyId)}
az role assignment create \\
  --role "Key Vault Crypto User" \\
  --assignee-object-id "${principalId}" \\
  --assignee-principal-type ServicePrincipal \\
  --scope "$KEY_VAULT_RESOURCE_ID"
"""
    AzCli(serviceConnection, "Grant Key Vault Crypto User for KMS", script, condition = condition)
}

# RevokeKeyVaultCryptoUser removes the role assignment created by GrantKeyVaultCryptoUser.
RevokeKeyVaultCryptoUser = lambda \
    serviceConnection: str, \
    subscription: str, \
    keyId: str, \
    principalId: str, \
    condition: str = Undefined \
    -> steps.Step {
    script = """
${resolveKeyVaultResourceId(subscription, keyId)}
az role assignment delete \\
  --role "Key Vault Crypto User" \\
  --assignee-object-id "${principalId}" \\
  --scope "$KEY_VAULT_RESOURCE_ID"
"""
    AzCli(serviceConnection, "Revoke Key Vault Crypto User for KMS", script, condition = condition)
}
