variable "route_table_config" {
  description = "Configuration for the route table"
  type = object({
    name                          = string
    bgp_route_propagation_enabled = optional(bool, true)
    routes = list(object({
      name                         = string
      address_prefix               = optional(string, null)
      address_prefix_publicip_name = optional(string, null)
      next_hop_type                = string
      next_hop_in_ip_address       = optional(string, null)
      next_hop_firewall_name       = optional(string, null)
    }))
    subnet_associations = list(object({
      subnet_name = string
    }))
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

variable "subnets_ids" {
  description = "Map of subnet names to subnet IDs from network module"
  type        = map(string)
}

variable "firewall_private_ips" {
  description = "Map of firewall names to their private IP addresses"
  type        = map(string)
  default     = {}
}

variable "public_ips" {
  description = "Map of public IP names to their objects containing id and ip_address"
  type = map(object({
    id         = string
    ip_address = string
  }))
}


variable "tags" {
  description = "Tags to apply to the route table"
  type        = map(string)
  default     = {}
}
