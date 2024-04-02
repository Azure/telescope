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

variable "vnet_id" {
  description = "Vnet id"
  type        = string
  default     = ""
}

variable "subnets" {
  description = "Maps of subnets"
  type        = map(string)
  default     = {}
}

variable "aks_config" {
  type = object({
    role           = string
    aks_name       = string
    dns_prefix     = string
    network_plugin = string
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string, null)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string, "Ubuntu")
      os_disk_type                 = optional(string, "Managed")
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
    })
    extra_node_pool = list(object({
      name         = string
      subnet_name  = optional(string, null)
      node_count   = number
      vm_size      = string
      os_sku       = optional(string, "Ubuntu")
      os_disk_type = optional(string, "Managed")
    }))
  })
}
