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

### `subnet_names`

- **Description:** List of Names of the subnets where the NAT gateway will be deployed.
- **Type:** list of strings

### `public_ip_names`

- **Description:** List of public IP addresses that are associated with the NAT gateway.
- **Type:** list of strings

### `tags`

- **Type:** Map of strings

## Usage Example

```hcl
module "nat_gateway" {
  source = "./nat-gateway"

  resource_group_name      = "my-rg"
  location                 = "eastus"
  nat_gateway_name         = "my-nat-gateway"
  subnet_names             = ["my-subnet"]
  public_ip_names          = ["my-public-ip"]

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
