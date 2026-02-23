variable "firewall_config_list" {
  description = "List of firewall configurations"
  type = list(object({
    name                  = string
    network_role          = optional(string)
    subnet_name           = optional(string)
    public_ip_names       = optional(list(string), [])
    sku_name              = optional(string, "AZFW_VNet")
    sku_tier              = optional(string, "Standard")
    firewall_policy_id    = optional(string)
    threat_intel_mode     = optional(string, "Alert")
    dns_proxy_enabled     = optional(bool, false)
    dns_servers           = optional(list(string))
    ip_configuration_name = optional(string, "firewall-ipconfig")
    nat_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = optional(string, "Dnat")
      rules = list(object({
        name                  = string
        source_addresses      = optional(list(string))
        source_ip_groups      = optional(list(string))
        destination_ports     = list(string)
        destination_addresses = list(string)
        translated_address    = string
        translated_port       = string
        protocols             = list(string)
      }))
    })))
    network_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = string
      rules = list(object({
        name                  = string
        source_addresses      = optional(list(string))
        source_ip_groups      = optional(list(string))
        destination_ports     = list(string)
        destination_addresses = optional(list(string))
        destination_fqdns     = optional(list(string))
        destination_ip_groups = optional(list(string))
        protocols             = list(string)
      }))
    })))
    application_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = string
      rules = list(object({
        name             = string
        source_addresses = optional(list(string))
        source_ip_groups = optional(list(string))
        target_fqdns     = optional(list(string))
        fqdn_tags        = optional(list(string))
        protocols = optional(list(object({
          port = string
          type = string
        })))
      }))
    })))
  }))
  default = []
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "subnets_map" {
  description = "Map of all subnets by name (for resolving subnet references)"
  type        = map(string)
}

variable "public_ips_map" {
  description = "Map of public IP names to their objects containing id and ip_address"
  type = map(object({
    id         = string
    ip_address = string
  }))
}

