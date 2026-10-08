variable "resource_group_name" {
  description = "Resource group containing the QAD-enabled AKS cluster"
  type        = string
}

variable "location" {
  description = "Azure region for the QAD-enabled AKS cluster"
  type        = string
}

variable "tags" {
  description = "Tags to apply to the QAD-enabled AKS cluster"
  type        = map(string)
  default     = {}
}

variable "qad_config" {
  description = "Configuration for creating an AKS cluster with Quick Attach/Detach enabled"
  type = object({
    role               = string
    aks_name           = string
    dns_prefix         = string
    api_version        = optional(string, "2026-07-02-preview")
    kubernetes_version = string
    identity_type      = optional(string, "SystemAssigned")
    sku = optional(object({
      name = optional(string, "Base")
      tier = optional(string, "Standard")
    }), {})
    network_profile = optional(object({
      network_plugin = optional(string, "kubenet")
      pod_cidr       = optional(string, null)
    }), {})
    system_node_pool = object({
      name        = optional(string, "systempool")
      count       = optional(number, 3)
      vm_size     = optional(string, "Standard_D2s_v3")
      os_type     = optional(string, "Linux")
      mode        = optional(string, "System")
      vm_set_type = optional(string, "VirtualMachineScaleSets")
      node_labels = optional(map(string), {})
    })
    user_node_pools = optional(list(object({
      name        = string
      count       = number
      vm_size     = string
      os_type     = optional(string, "Linux")
      mode        = optional(string, "User")
      vm_set_type = optional(string, "VirtualMachineScaleSets")
      node_labels = optional(map(string), {})
    })), [])
    dry_run = optional(bool, false)
  })
}
