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

variable "aks_rest_config" {
  type = object({
    role        = string
    aks_name    = string
    sku_tier    = string                                 # e.g., "Standard"
    sku_name    = optional(string, "Base")               # e.g., "Base"
    api_version = optional(string, "2026-01-02-preview") # ARM API version

    # Control plane scaling
    control_plane_scaling_size = optional(string, null) # e.g., "H2", "H4", "H8"

    # Kubernetes configuration
    kubernetes_version = optional(string, null)
    dns_prefix         = optional(string, null) # Defaults to aks_name if not set

    # Network configuration
    subnet_name         = optional(string, null)
    network_plugin      = optional(string, "azure")
    network_plugin_mode = optional(string, "overlay")

    # Identity
    managed_identity_name = optional(string, null)
    identity_type         = optional(string, "SystemAssigned")

    # Custom HTTP headers (e.g., "EtcdServersOverrides=hyperscale")
    custom_headers = optional(list(string), [])

    # Node pool configuration
    default_node_pool = optional(object({
      name       = string
      mode       = optional(string, "System")
      node_count = number
      vm_size    = string
      os_type    = optional(string, "Linux")
    }), null)
    extra_node_pool = optional(list(object({
      name       = string
      mode       = optional(string, "User")
      node_count = number
      vm_size    = string
      os_type    = optional(string, "Linux")
    })), [])

    # KMS encryption
    kms_config = optional(object({
      key_name       = string
      key_vault_name = string
      network_access = optional(string, "Public")
    }), null)

    # Disk Encryption Set for OS disk encryption with Customer-Managed Keys
    disk_encryption_set_name = optional(string, null)

    dry_run = optional(bool, false) # If true, only print the command without executing it. Useful for testing.
  })
}
