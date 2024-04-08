variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
  default     = ""
}

variable "vnet_id" {
  description = "Vnet id"
  type        = string
  default     = ""
}

variable "aks_config" {
  type = object({
    role           = string
    aks_name       = string
    dns_prefix     = string
    subnet_name    = string
    network_plugin = string
    sku_tier       = string
    default_node_pool = object({
      name                         = string
      node_count                   = number
      os_disk_type                 = string
      vm_size                      = string
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
    })
    extra_node_pool = list(object({
      name       = string
      node_count = number
      vm_size    = string
    }))
    role_assignment_list = optional(list(string), [])
  })
}
