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

variable "vm_sku" {
  description = "Value of the VM SKU"
  type        = string
  default     = "Standard_D2ds_v5"
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
    default_node_pool = object({
      name                         = string
      node_count                   = number
      os_disk_type                 = string
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
    })
    extra_node_pool = list(object({
      name       = string
      node_count = number
    }))
  })
}

