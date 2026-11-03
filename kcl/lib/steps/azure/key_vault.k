import azure_pipelines.ap.steps

# resolveKeyVaultResourceId returns a script that validates keyId and sets
# KEY_VAULT_RESOURCE_ID to the resource ID of the vault that holds the key.
# keyId must be a Key Vault key URI with an optional version.
# It may be a pipeline expression such as "\${{ parameters.kms_key_id }}", so it is validated at runtime.
resolveKeyVaultResourceId = lambda subscription: str, keyId: str -> str {
    """
KEY_ID="${keyId}"
if ! [[ "$KEY_ID" =~ ^https://[^/]+/keys/[^/]+(/[^/]+)?$ ]]; then
  echo "Key ID must be a Key Vault key URI (https://<vault>/keys/<key>[/<version>]); got '$KEY_ID'."
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

# GrantKeyVaultKmsAccess grants key data access and vault management access for CMK with infrastructure encryption.
# Vault role assignments outlive the identity; pair this with RevokeKeyVaultKmsAccess.
GrantKeyVaultKmsAccess = lambda \
    serviceConnection: str, \
    subscription: str, \
    keyId: str, \
    principalId: str, \
    condition: str = Undefined \
    -> steps.Step {
    script = """
${resolveKeyVaultResourceId(subscription, keyId)}
for role in "Key Vault Crypto User" "Key Vault Contributor"; do
  az role assignment create \\
    --role "$role" \\
    --assignee-object-id "${principalId}" \\
    --assignee-principal-type ServicePrincipal \\
    --scope "$KEY_VAULT_RESOURCE_ID"
done
"""
    AzCli(serviceConnection, "Grant Key Vault access for KMS", script, condition = condition)
}

# RevokeKeyVaultKmsAccess removes both vault role assignments created by GrantKeyVaultKmsAccess.
RevokeKeyVaultKmsAccess = lambda \
    serviceConnection: str, \
    subscription: str, \
    keyId: str, \
    principalId: str, \
    condition: str = Undefined \
    -> steps.Step {
    script = """
${resolveKeyVaultResourceId(subscription, keyId)}
for role in "Key Vault Crypto User" "Key Vault Contributor"; do
  az role assignment delete \\
    --role "$role" \\
    --assignee-object-id "${principalId}" \\
    --scope "$KEY_VAULT_RESOURCE_ID"
done
"""
    AzCli(serviceConnection, "Revoke Key Vault access for KMS", script, condition = condition)
}
