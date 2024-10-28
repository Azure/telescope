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
  default     = null
}

variable "vnet_id" {
  description = "Vnet id"
  type        = string
  default     = null
}

variable "subnets" {
  description = "Maps of subnets"
  type        = map(string)
  default     = {}
}

variable "aks_config" {
  type = object({
    role        = string
    aks_name    = string
    dns_prefix  = string
    subnet_name = optional(string, null)
    network_profile = optional(object({
      network_plugin      = optional(string, null)
      network_plugin_mode = optional(string, null)
      network_policy      = optional(string, null)
      network_dataplane   = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
    }))
    sku_tier = string
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string, null)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string, "Ubuntu")
      os_disk_type                 = optional(string, "Managed")
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
      max_pods                     = optional(number, null)
      node_labels                  = optional(map(string), {})
      min_count                    = optional(number, null)
      max_count                    = optional(number, null)
      auto_scaling_enabled         = optional(bool, false)
    })
    extra_node_pool = list(object({
      name                 = string
      subnet_name          = optional(string, null)
      node_count           = number
      vm_size              = string
      os_sku               = optional(string, "Ubuntu")
      os_disk_type         = optional(string, "Managed")
      max_pods             = optional(number, null)
      ultra_ssd_enabled    = optional(bool, false)
      zones                = optional(list(string), [])
      node_taints          = optional(list(string), [])
      node_labels          = optional(map(string), {})
      min_count            = optional(number, null)
      max_count            = optional(number, null)
      auto_scaling_enabled = optional(bool, false)
    }))
    role_assignment_list = optional(list(string), [])
    service_mesh_profile = optional(object({
      mode      = string
      revisions = list(string)
    }))
    kubernetes_version = optional(string, null)
    auto_scaler_profile = optional(object({
      balance_similar_node_groups      = optional(bool, false)
      expander                         = optional(string, null)
      max_graceful_termination_sec     = optional(string, null)
      max_node_provisioning_time       = optional(string, null)
      max_unready_nodes                = optional(number, null)
      max_unready_percentage           = optional(number, null)
      new_pod_scale_up_delay           = optional(string, null)
      scale_down_delay_after_add       = optional(string, null)
      scale_down_delay_after_delete    = optional(string, null)
      scale_down_delay_after_failure   = optional(string, null)
      scale_down_unneeded              = optional(string, null)
      scale_down_unready               = optional(string, null)
      scale_down_utilization_threshold = optional(string, null)
      scan_interval                    = optional(string, null)
      empty_bulk_delete_max            = optional(string, null)
      skip_nodes_with_local_storage    = optional(bool, true)
      skip_nodes_with_system_pods      = optional(bool, true)
    }))
  })
}
