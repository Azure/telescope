import azure_pipelines.ap.steps

# GrantKeyVaultCryptoUser grants an identity the Key Vault Crypto User role on the vault that
# holds keyId, so AKS can use the key for KMS etcd encryption.
# keyId must be a versioned key URI, e.g. https://<vault>.vault.azure.net/keys/<key>/<version>.
# It may be a pipeline expression such as "\${{ parameters.kms_key_id }}", so it is validated at runtime.
GrantKeyVaultCryptoUser = lambda \
    serviceConnection: str, \
    subscription: str, \
    keyId: str, \
    principalId: str, \
    condition: str = Undefined \
    -> steps.Step {
    script = """
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

az role assignment create \\
  --role "Key Vault Crypto User" \\
  --assignee-object-id "${principalId}" \\
  --assignee-principal-type ServicePrincipal \\
  --scope "$KEY_VAULT_RESOURCE_ID"
"""
    AzCli(serviceConnection, "Grant Key Vault Crypto User for KMS", script, condition = condition)
}
