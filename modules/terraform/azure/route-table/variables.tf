variable "route_table_config" {
  description = "Configuration for the route table"
  type = object({
    name                          = string
    bgp_route_propagation_enabled = optional(bool, true)
    routes = list(object({
      name                   = string
      address_prefix         = string
      next_hop_type          = string
      next_hop_in_ip_address = optional(string, null)
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

variable "tags" {
  description = "Tags to apply to the route table"
  type        = map(string)
  default     = {}
}
