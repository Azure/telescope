variable "firewall_config" {
  description = "Configuration for Azure Firewall"
  type = object({
    name                   = string
    sku_name               = optional(string, "AZFW_VNet")
    sku_tier               = optional(string, "Standard")
    firewall_policy_id     = optional(string, null)
    subnet_name            = string
    public_ip_name         = string
    ip_configuration_name  = optional(string, "firewall-ipconfig")
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

variable "subnets_map" {
  description = "Map of subnet names to subnet objects"
  type = map(object({
    id = string
  }))
}

variable "public_ips_map" {
  description = "Map of public IP names to public IP objects"
  type = map(object({
    id = string
  }))
}

variable "tags" {
  description = "Tags to apply to the firewall"
  type        = map(string)
  default     = {}
}
