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
  description = "Value of the subnet id"
  type        = string
  default     = null
}

variable "aks_cli_custom_config_path" {
  description = "Path to the custom configuration file for AKS CLI"
  type        = string
  default     = null
}

variable "public_ip_addresses" {
  description = "Map of public IP names to IP addresses for dynamic resolution"
  type        = map(string)
  default     = {}
}

variable "aks_cli_config" {
  type = object({
    role                          = string
    aks_name                      = string
    sku_tier                      = string
    subnet_name                   = optional(string, null)
    managed_identity_name         = optional(string, null)
    kubernetes_version            = optional(string, null)
    aks_custom_headers            = optional(list(string), [])
    use_custom_configurations     = optional(bool, false)
    use_aks_preview_cli_extension = optional(bool, true)
    use_aks_preview_private_build = optional(bool, false)
    default_node_pool = optional(object({
      name        = string
      node_count  = number
      vm_size     = string
      vm_set_type = optional(string, "VirtualMachineScaleSets")
    }), null)
    extra_node_pool = optional(
      list(object({
        name        = string
        node_count  = number
        vm_size     = string
        vm_set_type = optional(string, "VirtualMachineScaleSets")
        optional_parameters = optional(list(object({ # Refer to https://learn.microsoft.com/en-us/cli/azure/aks/nodepool?view=azure-cli-latest#az-aks-nodepool-add(aks-preview) for available parameters
          name  = string
          value = string
        })), [])
    })), [])
    optional_parameters = optional(list(object({  # Refer to https://learn.microsoft.com/en-us/cli/azure/aks?view=azure-cli-latest#az-aks-create(aks-preview) for available parameters
      name  = string
      value = string
    })), [])
    dry_run = optional(bool, false) # If true, only print the command without executing it. Useful for testing.
  })
}
