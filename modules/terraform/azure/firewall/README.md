# Azure Firewall Module

This module creates an Azure Firewall with optional NAT, Network, and Application rule collections.

## Features

- Azure Firewall with configurable SKU
- NAT rule collections for DNAT
- Network rule collections for Allow/Deny traffic filtering
- Application rule collections for controlling outbound web (HTTP/HTTPS) traffic
- Automatic rule management through separate resources

## Usage

```hcl
module "firewall" {
  source = "./firewall"
  firewall_config = {
    name                   = "my-firewall"
    sku_tier               = "Standard"
    subnet_id              = azurerm_subnet.firewall_subnet.id
    public_ip_address_id   = azurerm_public_ip.firewall_pip.id
    
    network_rule_collections = [
      {
        name     = "allow-outbound"
        priority = 100
        action   = "Allow"
        rules = [
          {
            name                  = "allow-internet"
            source_addresses      = ["10.0.0.0/16"]
            destination_addresses = ["*"]
            destination_ports     = ["*"]
            protocols             = ["Any"]
          }
        ]
      }
    ]
  }
  resource_group_name = "my-rg"
  location            = "eastus"
  tags                = { environment = "production" }
}
```

## Inputs

| Name | Description | Type | Required |
|------|-------------|------|----------|
| firewall_config | Firewall configuration object | object | yes |
| resource_group_name | Resource group name | string | yes |
| location | Azure region | string | yes |
| tags | Resource tags | map(string) | no |

## Outputs

| Name | Description |
|------|-------------|
| private_ip_address | Private IP address of the firewall |
