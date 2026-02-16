# Disk Encryption Set Module

This module creates an Azure Disk Encryption Set (DES) for encrypting AKS OS and data disks with Customer-Managed Keys (CMK).

## Overview

Azure Disk Encryption Sets allow you to encrypt managed disks using your own encryption keys stored in Azure Key Vault, providing enhanced control over encryption keys for compliance and security requirements.

**Reference**: [Azure AKS Disk Encryption with Customer-Managed Keys](https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys)

## Features

- Creates Disk Encryption Set with System-Assigned Managed Identity
- Supports multiple encryption types (single CMK, double encryption, confidential VMs)
- Automatic Key Vault RBAC role assignments for key access
- Optional automatic key rotation

## Usage

This module is typically invoked from the parent Azure module. It requires a Key Vault with encryption keys to be created first.

### Example Configuration

```hcl
# In parent module or tfvars file

# First, create the Key Vault with encryption key
key_vault_config_list = [
  {
    name = "mykeyvault"
    keys = [
      { key_name = "disk-encryption-key" }
    ]
  }
]

# Then, create the Disk Encryption Set
disk_encryption_set_config_list = [
  {
    name                      = "my-disk-encryption-set"
    key_vault_name            = "mykeyvault"
    key_name                  = "disk-encryption-key"
    encryption_type           = "EncryptionAtRestWithCustomerKey"
    auto_key_rotation_enabled = false
  }
]
```

### Using with AKS

Reference the Disk Encryption Set in your AKS configuration:

```hcl
aks_cli_config_list = [
  {
    role                     = "cluster"
    aks_name                 = "my-cluster"
    sku_tier                 = "Standard"
    disk_encryption_set_name = "my-disk-encryption-set"
    # ... other configuration
  }
]
```

## Input Variables

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `resource_group_name` | string | Yes | - | Name of the resource group |
| `location` | string | Yes | - | Azure region location |
| `tags` | map(string) | No | `{}` | Tags to apply to resources |
| `key_vaults` | map(any) | No | `{}` | Map of Key Vault configurations (passed from parent module) |
| `disk_encryption_set_config` | object | No | `null` | Disk Encryption Set configuration |

### disk_encryption_set_config Object

| Attribute | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | - | Name of the Disk Encryption Set (1-80 characters) |
| `key_vault_name` | string | Yes | - | Name of the Key Vault containing the encryption key |
| `key_name` | string | Yes | - | Name of the encryption key in the Key Vault |
| `encryption_type` | string | No | `"EncryptionAtRestWithCustomerKey"` | Type of encryption |
| `auto_key_rotation_enabled` | bool | No | `false` | Enable automatic key rotation |

### Encryption Types

| Type | Description |
|------|-------------|
| `EncryptionAtRestWithCustomerKey` | Disk is encrypted with customer-managed key only (default) |
| `EncryptionAtRestWithPlatformAndCustomerKeys` | Double encryption with both platform and customer-managed keys |
| `ConfidentialVmEncryptedWithCustomerKey` | For confidential VM scenarios |

## Outputs

| Output | Description |
|--------|-------------|
| `disk_encryption_set_id` | The resource ID of the Disk Encryption Set (used with `--node-osdisk-diskencryptionset-id` in AKS CLI) |

## Role Assignments

The module automatically creates the following RBAC role assignments for the Disk Encryption Set's managed identity:

| Role | Scope | Purpose |
|------|-------|---------|
| `Key Vault Crypto Service Encryption User` | Key Vault | Access to the Key Vault for cryptographic operations |
| `Key Vault Crypto Service Encryption User` | Key | Wrap/unwrap key operations on the specific encryption key |

## Dependencies

This module depends on:
- Key Vault module (must be created first with the required encryption key)
- Resource group must exist

## Architecture

```
┌─────────────────────────┐
│   Disk Encryption Set   │
│  (System-Assigned MI)   │
└───────────┬─────────────┘
            │
            │ RBAC: Key Vault Crypto
            │ Service Encryption User
            ▼
┌─────────────────────────┐
│       Key Vault         │
│  ┌───────────────────┐  │
│  │  Encryption Key   │  │
│  └───────────────────┘  │
└─────────────────────────┘
            │
            │ Used by
            ▼
┌─────────────────────────┐
│      AKS Cluster        │
│  (OS Disk Encryption)   │
└─────────────────────────┘
```

## Related Documentation

- [Azure Disk Encryption Set](https://learn.microsoft.com/en-us/azure/virtual-machines/disk-encryption-sets)
- [AKS Customer-Managed Keys](https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys)
- [Key Vault Module](../key-vault/)
- [AKS CLI Module](../aks-cli/README.md)
