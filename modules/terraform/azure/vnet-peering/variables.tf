variable "peering_enabled" {
  description = "Whether to create pairwise VNet peerings between all VNets in vnet_role_to_id."
  type        = bool
  default     = false
}

variable "vnet_role_to_id" {
  description = "Map of network role => VNet resource ID. Every pair (a, b) with a != b gets two peerings (a->b and b->a)."
  type        = map(string)
  default     = {}
}

variable "vnet_role_to_name" {
  description = "Map of network role => VNet name. Used to name the peering resource on the source VNet."
  type        = map(string)
  default     = {}
}

variable "resource_group_name" {
  description = "Resource group containing all VNets."
  type        = string
}
