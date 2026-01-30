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

variable "aks_aad_enabled" {
  description = "Indicates whether Azure Active Directory integration is enabled for AKS"
  type        = bool
  default     = false
}

variable "key_vaults" {
  description = "Map of Key Vault configurations with keys"
  type        = map(any)
  default     = {}
}

variable "disk_encryption_sets" {
  description = "Map of Disk Encryption Set names to their IDs for OS/data disk encryption. Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys"
  type        = map(string)
  default     = {}
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
    optional_parameters = optional(list(object({ # Refer to https://learn.microsoft.com/en-us/cli/azure/aks?view=azure-cli-latest#az-aks-create(aks-preview) for available parameters
      name  = string
      value = string
    })), [])
    kms_key_name             = optional(string, null)
    kms_key_vault_name       = optional(string, null)
    key_vault_network_access = optional(string, "Public")
    # Disk Encryption Set configuration for OS disk encryption with Customer-Managed Keys
    # Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys
    disk_encryption_set_name = optional(string, null) # Name of the Disk Encryption Set to use for OS disk encryption
    node_osdisk_type         = optional(string, null) # OS disk type: "Managed" or "Ephemeral"
    dry_run                  = optional(bool, false)  # If true, only print the command without executing it. Useful for testing.
  })
}

