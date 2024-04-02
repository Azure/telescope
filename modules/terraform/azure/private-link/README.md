# Azure Private Link Module

This module provisions Azure Private Link services and endpoints. It allows you to create and configure Private Link services and endpoints with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the Private Link resources will be created.
- **Type:** String
- **Default:** "cle-rg"

### `location`

- **Description:** Azure region where the Private Link resources will be deployed.
- **Type:** String
- **Default:** "eastus"

### `pls_name`

- **Description:** Name of the Private Link service.
- **Type:** String
- **Default:** "pls"

### `pls_subnet_id`

- **Description:** ID of the subnet for the Private Link service.
- **Type:** String
- **Default:** ""

### `pls_lb_fipc_id`

- **Description:** ID of the load balancer frontend IP configuration for the Private Link service.
- **Type:** String
- **Default:** ""

### `pe_name`

- **Description:** Name of the Private Endpoint.
- **Type:** String
- **Default:** "pe"

### `pe_subnet_id`

- **Description:** ID of the subnet for the Private Endpoint.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Usage Example

```hcl
module "private_link" {
  source = "./private-link"

  resource_group_name    = "my-rg"
  location               = "West Europe"
  pls_name               = "my-pls"
  pls_subnet_id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  pls_lb_fipc_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/loadBalancers/my-lb/frontendIPConfigurations/my-fipc"
  pe_name                = "my-pe"
  pe_subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

# Azure Private Link Module Outputs

This module provides the following output:

## `pls_id`

- **Description:** ID of the created Private Link service.
- **Type:** String
- **Example:** `/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/privateLinkServices/my-pls`

## Terraform Provider References

### Resources

- [azurerm_private_link_service](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/private_link_service)
- [azurerm_private_endpoint](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/private_endpoint)