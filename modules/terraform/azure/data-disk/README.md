# Data Disk Module

This module provisions data disks in Azure. It allows you to create and configure data disks with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the data disks will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the data disks will be deployed.
- **Type:** String
- **Default:** "East US"

### `data_disk_name`

- **Description:** A list of data disk names.
- **Type:** String
- **Default:** ""

### `data_disk_storage_account_type`

- **Description:** Storage account type for the data disks.
- **Type:** String
- **Default:** ""

### `data_disk_size_gb`

- **Description:** Size of the data disks in gigabytes.
- **Type:** String
- **Default:** ""

### `data_disk_iops_read_write`

- **Description:** IOPS (Input/Output Operations Per Second) for read and write operations.
- **Type:** Number
- **Default:** null

### `data_disk_mbps_read_write`

- **Description:** Throughput limit in MBps (Megabytes Per Second) for read and write operations.
- **Type:** Number
- **Default:** null

### `data_disk_iops_read_only`

- **Description:** IOPS (Input/Output Operations Per Second) for read-only operations.
- **Type:** Number
- **Default:** null

### `data_disk_mbps_read_only`

- **Description:** Throughput limit in MBps (Megabytes Per Second) for read-only operations.
- **Type:** Number
- **Default:** null

### `data_disk_tier`

- **Description:** Tier for the data disks.
- **Type:** String
- **Default:** null

### `tags`

- **Type:** Map of strings
- **Default:** None

### `zone`

- **Description:** Availability zone for the data disks.
- **Type:** Number
- **Default:** 1

## Usage Example

```hcl
module "data_disk" {
  source = "./data-disk"

  resource_group_name            = "my-rg"
  location                       = "West Europe"
  data_disk_name                 = "my-data-disk"
  data_disk_storage_account_type = "Standard_LRS"
  data_disk_size_gb              = "128"
  data_disk_iops_read_write      = 100
  data_disk_mbps_read_write      = 20
  data_disk_iops_read_only       = 50
  data_disk_mbps_read_only       = 10
  data_disk_tier                 = "Premium"
  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [azurerm_managed_disk Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/managed_disk)
