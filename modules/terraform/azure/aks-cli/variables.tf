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

variable "aks_cli_config" {
  type = object({
    role                          = string
    aks_name                      = string
    sku_tier                      = string
    aks_custom_headers            = optional(list(string), [])
    use_aks_preview_cli_extension = optional(bool, false)
    default_node_pool = optional(object({
      name        = string
      node_count  = number
      vm_size     = string
      vm_set_type = optional(string, "VirtualMachineScaleSets")
    }))
    extra_node_pool = optional(
      list(object({
        name        = string
        node_count  = number
        vm_size     = string
        vm_set_type = optional(string, "VirtualMachineScaleSets")
      })),
      []
    )
  })
}
