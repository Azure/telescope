# Network Security Rule Module

This module provisions network security rules in Azure. It allows you to create and configure network security rules with customizable settings.

## Input Variables

### `name`

- **Description:** Name for the network security rule.
- **Type:** String

### `priority`

- **Description:** Priority for the network security rule.
- **Type:** Number

### `direction`

- **Description:** Direction for the network security rule (Inbound/Outbound).
- **Type:** String

### `access`

- **Description:** Access for the network security rule (Allow/Deny).
- **Type:** String

### `protocol`

- **Description:** Protocol for the network security rule.
- **Type:** String

### `source_port_range`

- **Description:** Source port range for the network security rule.
- **Type:** String

### `destination_port_range`

- **Description:** Destination port range for the network security rule.
- **Type:** String

### `source_address_prefix`

- **Description:** Source address prefix for the network security rule.
- **Type:** String

### `destination_address_prefix`

- **Description:** Destination address prefix for the network security rule.
- **Type:** String

### `resource_group_name`

- **Description:** Resource group name for the network security rule.
- **Type:** String

### `network_security_group_name`

- **Description:** Network security group name for the network security rule.
- **Type:** String

## Usage Example

```hcl
module "network_security_rule" {
  source = "./network-security-rule"

  name                          = "my-nsr"
  priority                      = 100
  direction                     = "Inbound"
  access                        = "Allow"
  protocol                      = "TCP"
  source_port_range             = "*"
  destination_port_range        = "80"
  source_address_prefix         = "*"
  destination_address_prefix    = "*"
  resource_group_name           = "my-rg"
  network_security_group_name   = "my-nsg"
}
```

## Terraform Provider References

### Resources

- [azurerm_network_security_rule Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_security_rule)
