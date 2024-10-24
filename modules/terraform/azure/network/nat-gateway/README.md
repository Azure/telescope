# NAT Gateway Module

This module provisions a NAT gateway in Azure. It allows you to create and configure a NAT gateway with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the NAT gateway will be created.
- **Type:** String

### `location`

- **Description:** Azure region where the NAT gateway will be deployed.
- **Type:** String

### `nat_gateway_name`

- **Description:** Name of the NAT gateway.
- **Type:** String

### `subnet_id`

- **Description:** ID of the subnet where the NAT gateway will be deployed.
- **Type:** String

### `public_ip_address_id`

- **Description:** ID of the public IP address associated with the NAT gateway.
- **Type:** String

### `tags`

- **Type:** Map of strings

## Usage Example

```hcl
module "nat_gateway" {
  source = "./nat-gateway"

  resource_group_name      = "my-rg"
  location                 = "eastus"
  nat_gateway_name         = "my-nat-gateway"
  subnet_id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  public_ip_address_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/publicIPAddresses/my-public-ip"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [azurerm_nat_gateway Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/nat_gateway)
- [azurerm_nat_gateway_public_ip_association Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/nat_gateway_public_ip_association)
- [azurerm_subnet_nat_gateway_association Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/subnet_nat_gateway_association)
