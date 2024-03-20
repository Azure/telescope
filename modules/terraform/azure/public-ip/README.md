# Azure Public IP Module

This module provisions public IP addresses in Azure. It allows you to create one or more public IP addresses with customizable configurations.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the public IP address(es) will be created.
- **Type:** String
- **Default:** "cle-rg"

### `location`

- **Description:** Azure region where the public IP address(es) will be deployed.
- **Type:** String
- **Default:** "eastus"

### `public_ip_config_list`

- **Description:** Configuration for the public IP address(es).
- **Type:** List of objects
  - `name`: Name of the public IP address
  - `allocation_method`: Allocation method for the public IP (optional, default: "Static")
  - `sku`: SKU for the public IP (optional, default: "Standard")
  - `zones`: Availability zones for the public IP (optional, default: [])
- **Example:**
  ```hcl
  public_ip_config_list = [
    {
      name              = "example-ip-1"
      allocation_method = "Static"
      sku               = "Standard"
      zones             = ["1", "2"]
    },
    {
      name              = "example-ip-2"
      allocation_method = "Dynamic"
      sku               = "Basic"
    }
  ]
