# Azure Firewall Module

This module creates one or more Azure Firewalls with automatic subnet and public IP resolution, plus optional NAT, Network, and Application rule collections.

## Features

- **Multiple firewall support**: Create multiple firewalls in a single module call
- **Automatic dependency resolution**: Resolves subnet and public IP references from maps
- **Flexible rule collections**: Support for NAT, Network, and Application rule collections
- **SKU flexibility**: Configurable SKU name and tier (Standard/Premium)
- **DNS proxy support**: Optional DNS proxy with custom DNS servers
- **Threat intelligence**: Configurable threat intelligence mode
- **Firewall policies**: Optional firewall policy attachment

## Architecture

The module uses a mapping approach:
- `firewall_config_list`: List of firewall configurations
- `subnets_map`: Map of subnet names to subnet IDs (for resolution)
- `public_ips_map`: Map of public IP names to objects with `id` and `ip_address` (for resolution)

Each firewall config can reference subnets and public IPs by name, which are automatically resolved to their IDs.

## Usage

```hcl
module "firewall" {
  source = "./firewall"
  
  firewall_config_list = [
    {
      name                   = "main-firewall"
      network_role           = "hub"
      subnet_name            = "firewall-subnet"
      public_ip_names        = ["firewall-pip"]
      sku_tier               = "Standard"
      threat_intel_mode      = "Alert"
      dns_proxy_enabled      = false
      
      nat_rule_collections = [
        {
          name     = "inbound-nat"
          priority = 100
          action   = "Dnat"
          rules = [
            {
              name                  = "http-to-vm"
              source_addresses      = ["*"]
              destination_ports     = ["80"]
              destination_addresses = ["20.45.123.45"]
              translated_address    = "10.0.1.10"
              translated_port       = "80"
              protocols             = ["TCP"]
            }
          ]
        }
      ]
      
      network_rule_collections = [
        {
          name     = "allow-outbound"
          priority = 200
          action   = "Allow"
          rules = [
            {
              name                  = "allow-internet"
              source_addresses      = ["10.0.0.0/8"]
              destination_addresses = ["*"]
              destination_ports     = ["80", "443"]
              protocols             = ["TCP", "UDP"]
            }
          ]
        }
      ]
      
      application_rule_collections = [
        {
          name     = "web-rules"
          priority = 300
          action   = "Allow"
          rules = [
            {
              name             = "allow-https"
              source_addresses = ["10.0.0.0/8"]
              target_fqdns     = ["*.microsoft.com"]
              protocols = [
                { port = "443", type = "Https" }
              ]
            }
          ]
        }
      ]
    }
  ]
  
  subnets_map      = local.all_subnets
  public_ips_map   = module.public_ips.pip_ids
  resource_group_name = "my-rg"
  location         = "eastus"
  tags             = { environment = "production" }
}
```

## Inputs

| Name | Description | Type | Required |
|------|-------------|------|----------|
| `firewall_config_list` | List of firewall configurations | list(object) | Yes |
| `subnets_map` | Map of subnet names to subnet IDs | map(string) | Yes |
| `public_ips_map` | Map of public IP names to IP objects with `id` and `ip_address` | map(object) | Yes |
| `resource_group_name` | Resource group name | string | Yes |
| `location` | Azure region | string | Yes |
| `tags` | Resource tags | map(string) | No |

### Firewall Config Object Schema

```hcl
{
  name                     = string              # Firewall name
  network_role             = optional(string)    # Network role identifier
  subnet_name              = optional(string)    # Subnet name (resolved via subnets_map)
  public_ip_names          = optional(list)      # Public IP names (resolved via public_ips_map)
  sku_name                 = optional(string)    # Default: "AZFW_VNet"
  sku_tier                 = optional(string)    # Default: "Standard"
  firewall_policy_id       = optional(string)    # Attach firewall policy
  threat_intel_mode        = optional(string)    # Default: "Alert"
  dns_proxy_enabled        = optional(bool)      # Default: false
  dns_servers              = optional(list)      # Required if dns_proxy_enabled = true
  ip_configuration_name    = optional(string)    # Default: "firewall-ipconfig"
  nat_rule_collections     = optional(list)      # NAT rules
  network_rule_collections = optional(list)      # Network rules
  application_rule_collections = optional(list)  # Application rules
}
```

## Outputs

| Name | Description |
|------|-------------|
| `firewall_ids` | Map of firewall names to firewall IDs |
| `firewall_private_ips` | Map of firewall names to their private IP addresses |

## Notes

- **Subnet and Public IP Resolution**: If both a direct ID and a name are provided, the direct ID takes precedence
- **Rule Collections**: All rule types are optional. Provide only the rule collections you need
- **Multiple Firewalls**: Each firewall must have a unique name within the `firewall_config_list`
- **Dependencies**: The module automatically manages dependencies on subnets and public IPs
