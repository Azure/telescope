# AKS KMS Encryption with Azure Key Vault

This scenario demonstrates how to configure Azure Kubernetes Service (AKS) with ETCD encryption using Azure Key Vault Key Management Service (KMS).

## Overview

AKS supports encryption of etcd data at rest using Azure Key Vault keys. This provides an additional layer of security by allowing you to control and manage the encryption keys used to protect your Kubernetes secrets and configuration data.

## Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI installed (for CLI-based deployment)
- Terraform installed (for provider-based deployment)
- Proper RBAC permissions to:
  - Create Key Vaults
  - Assign roles (Key Vault Crypto Officer, Key Vault Crypto User, Key Vault Contributor)
  - Create AKS clusters

## Architecture

The setup includes:

1. **Azure Key Vault**: Stores the encryption key for AKS ETCD
2. **Encryption Key**: RSA-2048 key used for encrypting/decrypting ETCD data
3. **RBAC Roles**:
   - `Key Vault Crypto Officer`: Granted to the service principal creating the key
   - `Key Vault Crypto User`: Granted to the AKS cluster identity for encrypt/decrypt operations
   - `Key Vault Contributor`: (Optional) For key vault management operations

## Configuration

### Key Vault Configuration

```hcl
key_vault_config_list = [
  {
    role                        = "kms"
    name                        = "your-unique-kv-name"  # 3-24 characters, alphanumeric and hyphens
    sku_name                    = "premium"             # Use premium for better performance
    enable_rbac_authorization   = true                  # Required for RBAC-based access
    purge_protection_enabled    = true                  # Recommended for production
    key_name                    = "kms-encryption-key"
    key_type                    = "RSA"
    key_size                    = 2048
    grant_contributor_role      = true                  # Allows key vault purge operations
  }
]
```

### AKS Configuration with KMS

#### Option 1: Using Terraform Provider

```hcl
aks_config_list = [
  {
    role       = "server"
    aks_name   = "aks-kms-cluster"
    # ... other AKS configuration ...
    
    # Reference the Key Vault by role
    key_vault_kms_config = {
      key_vault_role           = "kms"        # Matches the role in key_vault_config_list
      key_vault_network_access = "Public"     # Or "Private" for private endpoint
    }
  }
]
```

#### Option 2: Using Azure CLI

```hcl
aks_cli_config_list = [
  {
    role                          = "server"
    aks_name                      = "aks-kms-cli-cluster"
    use_aks_preview_cli_extension = true
    # ... other AKS configuration ...
    
    # Reference the Key Vault by role
    key_vault_kms_config = {
      key_vault_role           = "kms"
      key_vault_network_access = "Public"
    }
  }
]
```

## How It Works

1. **Key Vault Creation**: Terraform creates the Key Vault with RBAC authorization enabled
2. **Key Generation**: An RSA-2048 encryption key is created in the Key Vault
3. **Role Assignment**: The current user/service principal is granted `Key Vault Crypto Officer` role to create keys
4. **AKS Deployment**: AKS cluster is created with KMS configuration
5. **Crypto User Access**: AKS cluster's managed identity is automatically granted `Key Vault Crypto User` role
6. **ETCD Encryption**: AKS uses the Key Vault key to encrypt/decrypt ETCD data

## Key Parameters

### Key Vault Parameters

- `role`: Unique identifier used to reference this Key Vault in AKS configuration
- `name`: Key Vault name (3-24 characters, globally unique)
- `sku_name`: Pricing tier (`standard` or `premium`)
- `enable_rbac_authorization`: Must be `true` for role-based access
- `purge_protection_enabled`: Prevents accidental deletion
- `soft_delete_retention_days`: Retention period for deleted keys (7-90 days)
- `key_name`: Name of the encryption key
- `key_type`: Type of key (RSA recommended)
- `key_size`: Size of the key (2048 or 4096)
- `grant_contributor_role`: Grants Key Vault Contributor role for management operations

### AKS KMS Parameters

- `key_vault_role`: References the `role` from `key_vault_config_list`
- `key_vault_network_access`: `Public` or `Private` (for private endpoint scenarios)

## Verification

After deployment, verify KMS encryption is enabled:

```bash
# Get AKS cluster credentials
az aks get-credentials --resource-group <rg-name> --name <aks-name>

# Check KMS configuration
az aks show --resource-group <rg-name> --name <aks-name> \
  --query "securityProfile.azureKeyVaultKms" -o json

# Expected output:
# {
#   "enabled": true,
#   "keyId": "https://<vault-name>.vault.azure.net/keys/<key-name>/<version>",
#   "keyVaultNetworkAccess": "Public"
# }
```

## Security Best Practices

1. **Use Premium SKU**: Better performance and HSM-backed keys
2. **Enable Purge Protection**: Prevents accidental key deletion
3. **Use Private Endpoints**: Set `key_vault_network_access = "Private"` for production
4. **Rotate Keys Regularly**: Implement key rotation policies
5. **Monitor Access**: Enable diagnostic logging for Key Vault
6. **Network Restrictions**: Configure `network_acls` to restrict access

## Troubleshooting

### Common Issues

1. **Key Vault Name Conflict**
   - Key Vault names are globally unique
   - Use a unique suffix or random identifier

2. **Permission Denied**
   - Ensure the service principal has appropriate RBAC roles
   - Verify `enable_rbac_authorization = true` is set

3. **AKS Creation Fails**
   - Check that Key Vault and key exist before AKS creation
   - Verify the `depends_on` relationship in Terraform

4. **Key Not Found**
   - Ensure the `key_vault_role` in AKS config matches the role in Key Vault config
   - Verify the key was created successfully

## References

- [Azure AKS KMS Documentation](https://learn.microsoft.com/en-us/azure/aks/use-kms-etcd-encryption)
- [Azure Key Vault RBAC](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide)
- [Terraform AzureRM Provider - Key Vault](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/key_vault)
- [Terraform AzureRM Provider - AKS](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster)

## Example Deployment

```bash
# Navigate to Terraform directory
cd modules/terraform/azure

# Initialize Terraform
terraform init

# Plan with your tfvars file
terraform plan \
  -var-file="../../../scenarios/perf-eval/aks-kms-encryption/terraform-inputs/azure.tfvars" \
  -var="json_input=$(cat ../../../scenarios/perf-eval/aks-kms-encryption/terraform-test-inputs/azure.json)"

# Apply configuration
terraform apply \
  -var-file="../../../scenarios/perf-eval/aks-kms-encryption/terraform-inputs/azure.tfvars" \
  -var="json_input=$(cat ../../../scenarios/perf-eval/aks-kms-encryption/terraform-test-inputs/azure.json)"
```
