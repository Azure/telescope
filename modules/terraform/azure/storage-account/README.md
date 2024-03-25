# Azure Storage Account Module

This module provisions Azure Storage Accounts with customizable configurations.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the storage account will be created.
- **Type:** String
- **Default:** "cle-rg"

### `location`

- **Description:** Azure region where the storage account will be deployed.
- **Type:** String
- **Default:** "eastus"

### `storage_account_name`

- **Description:** Name of the storage account.
- **Type:** String
- **Default:** ""

### `storage_account_tier`

- **Description:** Tier of the storage account (e.g., Standard, Premium).
- **Type:** String
- **Default:** ""

### `storage_account_kind`

- **Description:** Kind of the storage account (e.g., StorageV2, BlobStorage).
- **Type:** String
- **Default:** ""

### `storage_account_replication_type`

- **Description:** Replication type of the storage account (e.g., LRS, GRS).
- **Type:** String
- **Default:** ""

### `storage_share_config`

- **Description:** Configuration for storage shares.
- **Type:** Object
  - `name`: Name of the storage share
  - `quota`: Quota for the storage share
  - `access_tier`: Access tier for the storage share
  - `enabled_protocol`: Enabled protocol for the storage share
- **Default:** null

### `storage_network_rules_config`

- **Description:** Configuration for storage network rules.
- **Type:** Object
  - `default_action`: Default action for network rules
  - `virtual_network_subnet_ids`: List of virtual network subnet IDs
- **Default:** null

### `enable_https_traffic_only`

- **Description:** Enable HTTPS traffic only for the storage account.
- **Type:** Boolean
- **Default:** true

### `tags`

- **Description:** Tags to apply to the storage account resource.
- **Type:** Map of strings
- **Default:** {}

## Usage Example

```hcl
module "storage_account" {
  source = "./storage-account"
  
  resource_group_name           = "cle-rg"
  location                      = "eastus"
  storage_account_name          = "mystorageaccount"
  storage_account_tier          = "Standard"
  storage_account_kind          = "StorageV2"
  storage_account_replication_type = "LRS"
  
  storage_share_config = {
    name             = "myshare"
    quota            = 1024
    access_tier      = "Hot"
    enabled_protocol = "SMB"
  }
  
  storage_network_rules_config = {
    default_action             = "Allow"
    virtual_network_subnet_ids = ["subnet1-id", "subnet2-id"]
  }
  
  enable_https_traffic_only = true
  
  tags = {
    environment = "production"
    project     = "example"
  }
}
```

# Azure Storage Account Module Outputs

This module provides the following output:

## `storage_account_name`

- **Description:** Name of the created storage account.
- **Type:** String
- **Example:** `example-storage-account`

## Usage Example

```hcl
output "storage_account_name" {
  description = "Name of the storage account"
  value       = module.storage_account.storage_account_name
}
```

## Terraform Provider References

### Resources

- [azurerm_storage_account](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/storage_account)
- [azurerm_storage_share](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/storage_share)