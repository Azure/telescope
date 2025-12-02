# Azure Key Vault Module

This module provisions an Azure Key Vault with encryption keys for AKS KMS (Key Management Service) encryption. It enables ETCD encryption at rest using customer-managed keys.

## Features

- Creates Azure Key Vault with RBAC authorization enabled
- Generates encryption keys (RSA 2048-bit) for AKS KMS
- Automatically assigns required RBAC roles for key management
- Supports multiple encryption keys per Key Vault
- Adds random suffix to Key Vault name for global uniqueness

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the Key Vault will be created.
- **Type:** String
- **Required:** Yes

### `location`

- **Description:** Azure region where the Key Vault will be deployed.
- **Type:** String
- **Required:** Yes

### `tags`

- **Description:** Tags to apply to the Key Vault resources.
- **Type:** Map of strings
- **Default:** `{}`

### `key_vault_config`

- **Description:** Configuration for the Key Vault and encryption keys.
- **Type:** Object
  - `name`: Key Vault name (3-20 characters, a 4-character random suffix will be added)
  - `keys`: List of encryption keys to create
    - `key_name`: Name of the encryption key
- **Default:** `null`
- **Validation:** 
  - Key Vault name must be 3-20 characters
  - At least one key must be defined

## Outputs

### `key_vaults`

- **Description:** Key Vault information with all its keys and their IDs.
- **Type:** Object
  - `id`: The Azure Resource ID of the Key Vault
  - `keys`: Map of key names to their details
    - `id`: The Key Vault Key ID (versioned URL)
    - `resource_id`: The Azure Resource ID of the key

## Usage Example

### Basic Usage

```hcl
module "key_vault" {
  source = "./key-vault"

  resource_group_name = "my-rg"
  location            = "East US"
  
  key_vault_config = {
    name = "akskms"
    keys = [
      { key_name = "kms-encryption-key" }
    ]
  }

  tags = {
    environment = "production"
    project     = "aks-kms"
  }
}
```

### Multiple Keys

```hcl
module "key_vault" {
  source = "./key-vault"

  resource_group_name = "my-rg"
  location            = "East US"
  
  key_vault_config = {
    name = "akskms"
    keys = [
      { key_name = "kms-prod" },
      { key_name = "kms-dev" },
      { key_name = "kms-backup" }
    ]
  }

  tags = {
    environment = "production"
  }
}
```

### Integration with AKS Module

```hcl
# Define Key Vault
module "key_vault" {
  for_each = { "akskms" = { name = "akskms", keys = [{ key_name = "kms-key" }] } }

  source              = "./key-vault"
  resource_group_name = "my-rg"
  location            = "East US"
  key_vault_config    = each.value
  tags                = local.tags
}

# Use with AKS
module "aks" {
  source = "./aks"

  resource_group_name = "my-rg"
  location            = "East US"
  aks_config = {
    role               = "server"
    aks_name           = "my-aks"
    dns_prefix         = "myaks"
    sku_tier           = "Standard"
    kms_key_name       = "kms-key"
    kms_key_vault_name = "akskms"
    # ... other config
  }
  key_vaults = {
    for kv_name, kv in module.key_vault : kv_name => kv.key_vaults
  }
  # ... other variables
}
```

## RBAC Roles

This module automatically creates the following role assignments for the current user/service principal:

| Role | Purpose |
|------|---------|
| Key Vault Crypto Officer | Required to create and manage encryption keys |
| Key Vault Contributor | Required for Key Vault management and purge operations |

**Note:** Additional roles are assigned in the AKS module for the cluster identity:
- `Key Vault Crypto Service Encryption User` - For AKS to use the key for encryption
- `Key Vault Crypto User` - For AKS to access Key Vault cryptographic operations

## Key Properties

The encryption keys are created with the following properties:

| Property | Value |
|----------|-------|
| Key Type | RSA |
| Key Size | 2048 bits |
| Key Operations | encrypt, decrypt, wrapKey, unwrapKey |

## Terraform Provider References

### Resources

- [azurerm_key_vault Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/key_vault)
- [azurerm_key_vault_key Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/key_vault_key)
- [azurerm_role_assignment Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment)

### Data Sources

- [azurerm_client_config Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/data-sources/client_config)

## Related Documentation

- [Azure AKS KMS Encryption](https://learn.microsoft.com/en-us/azure/aks/use-kms-etcd-encryption)
- [Azure Key Vault Overview](https://learn.microsoft.com/en-us/azure/key-vault/general/overview)
- [Azure RBAC for Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide)
