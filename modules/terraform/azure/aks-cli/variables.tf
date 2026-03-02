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

variable "disk_encryption_sets" {
  description = "Map of Disk Encryption Set names to their IDs for OS/data disk encryption. Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys"
  type        = map(string)
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
    # When true, use `az rest` (rest_call_config) instead of `az aks create` to provision the cluster
    use_az_rest = optional(bool, false)
    # Custom Azure Resource Manager endpoint. When set, runs `az cloud update --endpoint-resource-manager` before provisioning.
    endpoint_resource_manager = optional(string, null)
    # REST API calls to execute after AKS cluster creation using `az rest`
    # URI is auto-built: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerService/managedClusters/{aks_name}?api-version={api_version}
    rest_call_config = optional(object({
      method      = string                     # HTTP method: GET, PUT, POST, PATCH, DELETE
      api_version = string                     # Azure API version, e.g. "2024-01-01"
      headers     = optional(list(string), []) # List of "key=value" strings, e.g. ["Content-Type=application/json"]
      body_json_path = optional(string, null)       # Path to a JSON file for the request body
    }), null)
    dry_run = optional(bool, false) # If true, only print the command without executing it. Useful for testing.
    # Disk Encryption Set configuration for OS disk encryption with Customer-Managed Keys
    disk_encryption_set_name = optional(string, null) # Name of the Disk Encryption Set to use for OS disk encryption
  })

  validation {
    condition = (
      !var.aks_cli_config.use_az_rest || var.aks_cli_config.rest_call_config != null
    )
    error_message = "rest_call_config (with method and api_version) must be provided when use_az_rest is true."
  }
}

