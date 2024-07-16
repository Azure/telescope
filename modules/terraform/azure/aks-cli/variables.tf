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
    role               = string
    aks_name           = string
    sku_tier           = string
    aks_custom_headers = optional(list(string), [])
    default_node_pool = object({
      name       = string
      node_count = number
      vm_size    = string
    })
    extra_node_pool = optional(
      list(object({
        name       = string
        node_count = number
        vm_size    = string
      })),
      []
    )
  })
}
