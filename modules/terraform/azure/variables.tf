variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id                       = string
    region                       = string
    user_data_path               = optional(string, null)
    aks_sku_tier                 = optional(string, null)
    aks_kubernetes_version       = optional(string, null)
    aks_network_policy           = optional(string, null)
    aks_network_dataplane        = optional(string, null)
    aks_custom_headers           = optional(list(string), [])
    k8s_machine_type             = optional(string, null)
    k8s_os_disk_type             = optional(string, null)
    encoded_custom_configuration = optional(string, null)
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
        optional_parameters = optional(list(object({
          name  = string
          value = string
        })), [])
      }))
    )
  })

  validation {
    condition = (var.json_input.aks_network_policy == null
      || (try(contains(["azure", "cilium"], var.json_input.aks_network_policy), false)
      && (var.json_input.aks_network_policy == var.json_input.aks_network_dataplane || var.json_input.aks_network_dataplane == null))
    )
    # ref: https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/kubernetes_cluster#network_policy-1
    error_message = "If aks_network_policy is 'azure' or 'cilium', aks_network_dataplane must match or be null"
  }
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

variable "public_ip_config_list" {
  description = "A list of public IP names"
  type = list(object({
    name              = string
    count             = optional(number, 1)
    allocation_method = optional(string, "Static")
    sku               = optional(string, "Standard")
    zones             = optional(list(string), [])
  }))
  default = []
}

variable "network_config_list" {
  description = "Configuration for creating the server network."
  type = list(object({
    role               = string
    vnet_name          = string
    vnet_address_space = string
    subnet = list(object({
      name                         = string
      address_prefix               = string
      service_endpoints            = optional(list(string))
      pls_network_policies_enabled = optional(bool)
      delegations = optional(list(object({
        name                       = string
        service_delegation_name    = string
        service_delegation_actions = list(string)
      })))
    }))
    network_security_group_name = string
    nic_public_ip_associations = list(object({
      nic_name              = string
      subnet_name           = string
      ip_configuration_name = string
      public_ip_name        = string
      count                 = optional(number, 1)
    }))
    nsr_rules = list(object({
      name                       = string
      priority                   = number
      direction                  = string
      access                     = string
      protocol                   = string
      source_port_range          = string
      destination_port_range     = string
      source_address_prefix      = string
      destination_address_prefix = string
    }))
    nat_gateway_associations = optional(list(object({
      nat_gateway_name = string
      public_ip_names  = list(string)
      subnet_names     = list(string)
    })))
  }))
  default = []
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
      network_dataplane   = optional(string, null)
      outbound_type       = optional(string, null)
      pod_cidr            = optional(string, null)
      service_cidr        = optional(string, null)
      dns_service_ip      = optional(string, null)
    }))
    service_mesh_profile = optional(object({
      mode      = string
      revisions = list(string)
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
      node_labels                  = optional(map(string), {})
      min_count                    = optional(number, null)
      max_count                    = optional(number, null)
      auto_scaling_enabled         = optional(bool, false)
    })
    extra_node_pool = list(object({
      name                 = string
      subnet_name          = optional(string)
      node_count           = number
      vm_size              = string
      os_sku               = optional(string)
      os_disk_type         = optional(string)
      max_pods             = optional(number)
      ultra_ssd_enabled    = optional(bool, false)
      zones                = optional(list(string), [])
      node_taints          = optional(list(string), [])
      node_labels          = optional(map(string), {})
      min_count            = optional(number, null)
      max_count            = optional(number, null)
      auto_scaling_enabled = optional(bool, false)
    }))
    role_assignment_list      = optional(list(string), [])
    oidc_issuer_enabled       = optional(bool, false)
    workload_identity_enabled = optional(bool, false)
    kubernetes_version        = optional(string, null)
    edge_zone                 = optional(string, null)
    auto_scaler_profile = optional(object({
      balance_similar_node_groups      = optional(bool, false)
      expander                         = optional(string, "random")
      max_graceful_termination_sec     = optional(string, "600")
      max_node_provisioning_time       = optional(string, "15m")
      max_unready_nodes                = optional(number, 3)
      max_unready_percentage           = optional(number, 45)
      new_pod_scale_up_delay           = optional(string, "10s")
      scale_down_delay_after_add       = optional(string, "10m")
      scale_down_delay_after_delete    = optional(string, "10s")
      scale_down_delay_after_failure   = optional(string, "3m")
      scale_down_unneeded              = optional(string, "10m")
      scale_down_unready               = optional(string, "20m")
      scale_down_utilization_threshold = optional(string, "0.5")
      scan_interval                    = optional(string, "10s")
      empty_bulk_delete_max            = optional(string, "10")
      skip_nodes_with_local_storage    = optional(bool, true)
      skip_nodes_with_system_pods      = optional(bool, true)
    }))
  }))
  default = []
}

variable "aks_cli_config_list" {
  type = list(object({
    role     = string
    aks_name = string
    sku_tier = string

    managed_identity_name         = optional(string, null)
    subnet_name                   = optional(string, null)
    kubernetes_version            = optional(string, null)
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
        optional_parameters = optional(list(object({
          name  = string
          value = string
        })), [])
    })), [])
    optional_parameters = optional(list(object({
      name  = string
      value = string
    })), [])
  }))
  default = []
}

variable "aks_arm_deployment_config_list" {
  description = "AKS ARM deployment configuration"
  type = list(object({
    name            = string
    parameters_path = string
  }))
}
