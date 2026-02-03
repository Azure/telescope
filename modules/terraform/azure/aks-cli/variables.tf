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

variable "subnets_map" {
  description = "Map of subnet names to subnet objects"
  type        = map(any)
  default     = {}
}

variable "aks_cli_custom_config_path" {
  description = "Path to the custom configuration file for AKS CLI"
  type        = string
  default     = null
}

variable "key_vaults" {
  description = "Map of Key Vault configurations with keys"
  type        = map(any)
  default     = {}
}


variable "aks_aad_enabled" {
  description = "Indicates whether Azure Active Directory integration is enabled for AKS"
  type        = bool
  default     = false
}

variable "aks_cli_config" {
  type = object({
    role                              = string
    aks_name                          = string
    sku_tier                          = string
    subnet_name                       = optional(string, null)
    managed_identity_name             = optional(string, null)
    kubernetes_version                = optional(string, null)
    aks_custom_headers                = optional(list(string), [])
    use_custom_configurations         = optional(bool, false)
    use_aks_preview_cli_extension     = optional(bool, true)
    use_aks_preview_private_build     = optional(bool, false)
    api_server_subnet_name            = optional(string, false)
    enable_apiserver_vnet_integration = optional(bool, false)
    default_node_pool = optional(object({
      name         = string
      node_count   = number
      vm_size      = string
      vm_set_type  = optional(string, "VirtualMachineScaleSets")
      os_disk_type = optional(string, "Managed")
    }), null)
    extra_node_pool = optional(
      list(object({
        name         = string
        node_count   = number
        vm_size      = string
        vm_set_type  = optional(string, "VirtualMachineScaleSets")
        os_disk_type = optional(string, "Managed")
        optional_parameters = optional(list(object({ # Refer to https://learn.microsoft.com/en-us/cli/azure/aks/nodepool?view=azure-cli-latest#az-aks-nodepool-add(aks-preview) for available parameters
          name  = string
          value = string
        })), [])
    })), [])
    optional_parameters = optional(list(object({ # Refer to https://learn.microsoft.com/en-us/cli/azure/aks?view=azure-cli-latest#az-aks-create(aks-preview) for available parameters
      name  = string
      value = string
    })), [])
    kms_config = optional(object({
      key_name       = string
      key_vault_name = string
      network_access = optional(string, "Public")
    }), null)
    dry_run = optional(bool, false) # If true, only print the command without executing it. Useful for testing.
  })
}

