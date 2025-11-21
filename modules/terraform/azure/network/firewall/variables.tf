variable "firewall_config" {
  description = "Firewall configuration"
  type = object({
    name                   = string
    sku_name               = optional(string, "AZFW_VNet")
    sku_tier               = string
    firewall_policy_id     = optional(string)
    ip_configuration_name  = optional(string, "ip_config")
    subnet_id              = string
    public_ip_address_id   = string
    nat_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = string
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
  })
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
