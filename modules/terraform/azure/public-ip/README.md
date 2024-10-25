# Azure Public IP Module

This module provisions public IP addresses in Azure. It allows you to create one or more public IP addresses with customizable configurations.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the public IP address(es) will be created.
- **Type:** String

### `location`

- **Description:** Azure region where the public IP address(es) will be deployed.
- **Type:** String

### `public_ip_config_list`

- **Description:** Configuration for the public IP address(es).
- **Type:** List of objects
  - `name`: Name of the public IP address
  - `allocation_method`: Allocation method for the public IP (optional, default: "Static")
  - `sku`: SKU for the public IP (optional, default: "Standard")
  - `zones`: Availability zones for the public IP (optional, default: [])
  - `count`: Optional parameter to specify how many copies of the module to create, with the name acting as prefix
- **Example:**
  ```
  public_ip_config_list = [
    {
      name              = "example-ip-1"
      allocation_method = "Static"
      sku               = "Standard"
      zones             = ["1", "2"]
    },
    {
      name              = "example-ip-copy"
      allocation_method = "Dynamic"
      sku               = "Basic"
      count             = 2 # will copy this pip with names example-ip-copy-1 and example-ip-copy-2
    }
  ]

#  Outputs

This module provides the following outputs:

## `pip_ids`

- **Description:** IDs of the created public IP addresses.
- **Type:** Map
- **Example:**
  ```hcl
  {
    "example-ip-1" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/cle-rg/providers/Microsoft.Network/publicIPAddresses/example-ip-1"
    "example-ip-2" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/cle-rg/providers/Microsoft.Network/publicIPAddresses/example-ip-2"
  }
```

## Terraform Provider References

### Resources

- [azurerm_public_ip](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/public_ip)

