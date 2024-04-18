variable "json_input" {
  description = "value of the json input"
  type = object({
    owner                            = string
    run_id                           = string
    region                           = string
    public_key_path                  = string
    machine_type                     = optional(string)
    accelerated_networking           = optional(bool)
    user_data_path                   = optional(string)
    data_disk_storage_account_type   = optional(string)
    data_disk_size_gb                = optional(string)
    data_disk_tier                   = optional(string)
    data_disk_iops_read_write        = optional(number)
    data_disk_mbps_read_write        = optional(number)
    data_disk_iops_read_only         = optional(number)
    data_disk_mbps_read_only         = optional(number)
    data_disk_caching                = optional(string)
    ultra_ssd_enabled                = optional(bool)
    storage_account_tier             = optional(string)
    storage_account_kind             = optional(string)
    storage_account_replication_type = optional(string)
    storage_share_quota              = optional(number)
    storage_share_access_tier        = optional(string)
    storage_share_enabled_protocol   = optional(string)
  })
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

variable "public_ip_config_list" {
  description = "A list of public IP names"
  type = list(object({
    name              = string
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
    }))
    network_security_group_name = string
    nic_public_ip_associations = list(object({
      nic_name              = string
      subnet_name           = string
      ip_configuration_name = string
      public_ip_name        = string
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
      public_ip_name   = string
      subnet_name      = string
    })))
  }))
  default = []
}

variable "appgateway_config_list" {
  description = "List of app gateway configurations"
  type = list(object({
    role            = string
    appgateway_name = string
    public_ip_name  = string
    subnet_name     = string
    appgateway_probes = list(object({
      name     = string
      protocol = string
    }))
    appgateway_backend_address_pool = list(object({
      name         = string
      ip_addresses = list(string)
    }))
    appgateway_frontendport = object({
      name = string
      port = string
    })
    appgateway_backend_http_settings = list(object({
      name                  = string
      host_name             = string
      cookie_based_affinity = string
      port                  = number
      protocol              = string
      request_timeout       = number
      probe_name            = string
    }))
    appgateway_http_listeners = list(object({
      name                           = string
      frontend_ip_configuration_name = string
      frontend_port_name             = string
      protocol                       = string
      host_name                      = string
    }))
    appgateway_request_routing_rules = list(object({
      name                       = string
      priority                   = number
      rule_type                  = string
      http_listener_name         = string
      backend_address_pool_name  = string
      backend_http_settings_name = string
    }))
  }))
  default = []
}

variable "aks_config_list" {
  type = list(object({
    role           = string
    aks_name       = string
    subnet_name    = string
    dns_prefix     = string
    network_plugin = string
    sku_tier       = string
    default_node_pool = object({
      name                         = string
      node_count                   = number
      vm_size                      = string
      os_disk_type                 = string
      only_critical_addons_enabled = bool
      temporary_name_for_rotation  = string
    })
    extra_node_pool = list(object({
      name       = string
      node_count = number
      vm_size    = string
    }))
    role_assignment_list = optional(list(string), [])
  }))
  default = []
}

variable "loadbalancer_config_list" {
  description = "List of Loadbalancer configurations"
  type = list(object({
    role                  = string
    loadbalance_name      = string
    public_ip_name        = optional(string)
    loadbalance_pool_name = string
    probe_protocol        = string
    probe_port            = string
    probe_request_path    = string
    subnet_name           = optional(string)
    is_internal_lb        = optional(bool)
    lb_rules = list(object({
      type                    = string
      role                    = string
      frontend_port           = number
      backend_port            = number
      protocol                = string
      rule_count              = number
      enable_tcp_reset        = bool
      idle_timeout_in_minutes = number
    }))
  }))
  default = []
}

variable "vm_config_list" {
  description = "List of configuration for virtual machines"
  type = list(object({
    role             = string
    vm_name          = string
    nic_name         = string
    admin_username   = string
    info_column_name = optional(string)
    zone             = optional(number)
    source_image_reference = object({
      publisher = string
      offer     = string
      sku       = string
      version   = string
    })
    create_vm_extension = bool
  }))
  default = []
}

variable "vmss_config_list" {
  description = "List of configuration for virtual machine scale sets"
  type = list(object({
    role                   = string
    vmss_name              = string
    admin_username         = string
    nic_name               = string
    subnet_name            = string
    loadbalancer_pool_name = string
    ip_configuration_name  = string
    number_of_instances    = number
    source_image_reference = object({
      publisher = string
      offer     = string
      sku       = string
      version   = string
    })
  }))
  default = []
}

variable "nic_backend_pool_association_list" {
  description = "List of configuration for nic backend pool associations"
  type = list(object({
    nic_name              = string
    backend_pool_name     = string
    vm_name               = string
    ip_configuration_name = string
  }))
  default = []
}

variable "data_disk_config_list" {
  description = "List of configuration for data disks"
  type = list(object({
    disk_name = string
    zone      = number
  }))
  default = []
}

variable "data_disk_association_list" {
  description = "List of configuration for data_disk associations"
  type = list(object({
    data_disk_name = string
    vm_name        = string
  }))
  default = []
}

variable "storage_account_name_prefix" {
  type    = string
  default = null
}

variable "private_link_conf" {
  description = "configuration for private link service and private endpoint"
  type = object({
    pls_name             = string
    pls_loadbalance_role = string
    pls_subnet_name      = string

    pe_name        = string
    pe_subnet_name = string
  })
  default = null
}

variable "pe_config" {
  description = "configuration for a private endpoint"
  type = object({
    pe_name              = string
    pe_subnet_name       = string
    psc_name             = string
    is_manual_connection = bool
    subresource_names    = optional(list(string))
  })
  default = null
}
