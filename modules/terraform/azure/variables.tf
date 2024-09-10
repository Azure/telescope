variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id = string
    region = string
    aks_cli_system_node_pool = optional(object({
      name        = string
      node_count  = number
      vm_size     = string
      vm_set_type = string
    }))
    aks_cli_user_node_pool = optional(
      list(object({
        name        = string
        node_count  = number
        vm_size     = string
        vm_set_type = string
      }))
    )
  })
}

variable "owner" {
  description = "Owner of the scenario"
  type        = string
  default     = "azure_devops"
}

variable "scenario_name" {
  description = "Name of the scenario"
  type        = string
  default     = ""
}

variable "scenario_type" {
  description = "value of the scenario type"
  type        = string
  default     = ""
}

variable "deletion_delay" {
  description = "Time duration after which the resources can be deleted (e.g., '1h', '2h', '4h')"
  type        = string
  default     = "2h"
}

variable "aks_config_list" {
  type = list(object({
    role        = string
    aks_name    = string
    subnet_name = optional(string)
    dns_prefix  = string
    network_profile = optional(object({
      network_plugin      = optional(string, null)
      network_plugin_mode = optional(string, null)
      network_policy      = optional(string, null)
      ebpf_data_plane     = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
    }))
    auto_scaler_profile = optional(object({
      balance_similar_node_groups      = optional(bool, null)
      expander                         = optional(string, null)
      max_graceful_termination_sec     = optional(string, null)
      max_node_provisioning_time       = optional(string, null)
      max_unready_nodes                = optional(number, null)
      max_unready_percentage           = optional(number, null)
      new_pod_scale_up_delay           = optional(string, null)
      scale_down_delay_after_add       = optional(string, null)
      scale_down_delay_after_delete    = optional(string, null)
      scale_down_delay_after_failure   = optional(string, null)
      scan_interval                    = optional(string, null)
      scale_down_unneeded              = optional(string, null)
      scale_down_unready               = optional(string, null)
      scale_down_utilization_threshold = optional(string, null)
      empty_bulk_delete_max            = optional(string, null)
      skip_nodes_with_local_storage    = optional(bool, null)
      skip_nodes_with_system_pods      = optional(bool, null)
    }))
    service_mesh_profile = optional(object({
      mode = string
    }))
    sku_tier = string
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string)
      os_disk_type                 = optional(string)
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
      max_pods                     = optional(number)
      enable_auto_scaling          = optional(bool, false)
      min_count                    = optional(number, null)
      max_count                    = optional(number, null)
    })
    extra_node_pool = list(object({
      name                = string
      subnet_name         = optional(string)
      node_count          = number
      vm_size             = string
      os_sku              = optional(string)
      os_disk_type        = optional(string)
      max_pods            = optional(number)
      ultra_ssd_enabled   = optional(bool, false)
      zones               = optional(list(string), [])
      enable_auto_scaling = optional(bool, false)
      min_count           = optional(number, null)
      max_count           = optional(number, null)
    }))
    role_assignment_list = optional(list(string), [])
  }))
  default = []
}

variable "aks_cli_config_list" {
  type = list(object({
    role     = string
    aks_name = string
    sku_tier = string

    aks_custom_headers            = optional(list(string))
    use_aks_preview_cli_extension = optional(bool, true)

    default_node_pool = object({
      name        = string
      node_count  = number
      vm_size     = string
      vm_set_type = optional(string, "VirtualMachineScaleSets")
    })
    extra_node_pool = optional(
      list(object({
        name        = string
        node_count  = number
        vm_size     = string
        vm_set_type = optional(string, "VirtualMachineScaleSets")
    })), [])
    optional_parameters = optional(list(object({
      name  = string
      value = string
    })), [])
  }))
  default = []
}
