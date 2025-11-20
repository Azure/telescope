# Azure Firewall Module

This module creates an Azure Firewall instance.

## Features

- Azure Firewall with configurable SKU (Standard, Premium, Basic)
- Integration with existing VNet and subnet (requires AzureFirewallSubnet)
- Public IP association for outbound connectivity
- Optional Firewall Policy integration

## Requirements

- **Subnet**: Must be named `AzureFirewallSubnet` in your VNet
- **Public IP**: Standard SKU public IP address
- **Firewall Policy**: Optional, for centralized rule management

## Usage

```hcl
module "firewall" {
  source = "./firewall"

  firewall_config = {
    name           = "my-firewall"
    sku_name       = "AZFW_VNet"
    sku_tier       = "Standard"
    subnet_name    = "AzureFirewallSubnet"
    public_ip_name = "firewall-pip"
  }
  
  resource_group_name = "my-rg"
  location            = "eastus2"
  subnets_map         = { "AzureFirewallSubnet" = { id = "/subscriptions/.../AzureFirewallSubnet" } }
  public_ips_map      = { "firewall-pip" = { id = "/subscriptions/.../firewall-pip" } }
}
```

## Outputs

- `firewall_id`: Resource ID of the firewall
- `firewall_private_ip`: Private IP address (use this as next hop in UDR routes)
- `firewall_name`: Name of the firewall

## Notes

- The subnet **must** be named `AzureFirewallSubnet` (Azure requirement)
- Subnet address space should be at least /26
- For UDR scenarios, use `firewall_private_ip` as the `next_hop_in_ip_address` in your route table
