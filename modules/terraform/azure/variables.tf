variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id             = string
    region             = string
    aks_sku_tier       = optional(string, "Standard")
    aks_network_policy = optional(string, null)
    aks_custom_headers = optional(list(string), [])
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

  validation {
    condition     = length(var.scenario_name) <= 30
    error_message = "scenario_name should be within 30 characters"
  }
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
      network_plugin      = optional(string, "azure")
      network_plugin_mode = optional(string, "overlay")
      network_policy      = optional(string, null)
      ebpf_data_plane     = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
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
      os_sku                       = optional(string, "Ubuntu")
      os_disk_type                 = optional(string, "Managed")
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = optional(string, "defaulttmp")
      max_pods                     = optional(number, 110)
      min_count                    = optional(number, 2)
      max_count                    = optional(number, 5)
      enable_auto_scaling          = optional(bool, true)
    })
    extra_node_pool = list(object({
      name              = string
      subnet_name       = optional(string)
      node_count        = number
      vm_size           = string
      os_sku            = optional(string, "Ubuntu")
      os_disk_type      = optional(string, "Managed")
      max_pods          = optional(number, 110)
      min_count         = optional(number, 2)
      max_count         = optional(number, 100)
      ultra_ssd_enabled = optional(bool, false)
      zones             = optional(list(string), [])
      node_taints       = optional(list(string), [])
    }))
    role_assignment_list = optional(list(string), [])
    kubernetes_version   = optional(string, null)
  }))
  default = []
}

variable "aks_cli_config_list" {
  type = list(object({
    role     = string
    aks_name = string
    sku_tier = string

    aks_custom_headers            = optional(list(string), [])
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
