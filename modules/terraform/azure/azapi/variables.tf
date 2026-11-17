variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "azapi_config" {
  description = "Configuration for creating an AKS cluster via Azure REST API (AzAPI provider). aad_enabled opts into managed Microsoft Entra ID integration and Azure RBAC for Kubernetes authorization."
  type = object({
    role                   = string
    aks_name               = string
    dns_prefix             = string
    api_version            = optional(string, "2025-10-01")
    aad_enabled            = optional(bool, false)
    metrics_reader_enabled = optional(bool, false)

    sku = optional(object({
      name = optional(string, "Base")
      tier = optional(string, "Standard")
    }), {})

    identity_type = optional(string, "SystemAssigned")

    kubernetes_version = optional(string, null)

    network_profile = optional(object({
      network_plugin      = optional(string, "azure")
      network_plugin_mode = optional(string, "overlay")
    }), {})

    default_node_pool = object({
      name    = optional(string, "systempool1")
      count   = optional(number, 3)
      vm_size = optional(string, "Standard_D2s_v5")
      os_type = optional(string, "Linux")
      mode    = optional(string, "System")
    })

    control_plane_scaling_profile = optional(object({
      scaling_size = string
    }), null)
  })

  validation {
    condition     = !var.azapi_config.metrics_reader_enabled || var.azapi_config.aad_enabled
    error_message = "metrics_reader_enabled requires aad_enabled."
  }
}
