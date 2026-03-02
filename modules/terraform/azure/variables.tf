variable "json_input" {
  description = "value of the json input"
  type = object({
    run_id                            = string
    region                            = string
    aks_sku_tier                      = optional(string, null)
    aks_kubernetes_version            = optional(string, null)
    aks_network_policy                = optional(string, null)
    aks_network_dataplane             = optional(string, null)
    aks_aad_enabled                   = optional(bool, null)
    aks_custom_headers                = optional(list(string), [])
    k8s_machine_type                  = optional(string, null)
    k8s_os_disk_type                  = optional(string, null)
    enable_apiserver_vnet_integration = optional(bool, false)
    public_key_path                   = optional(string, null)

    aks_cli_system_node_pool = optional(object({
      name         = string
      node_count   = number
      vm_size      = string
      vm_set_type  = string
      os_disk_type = optional(string, "Managed")
    }))
    aks_cli_user_node_pool = optional(
      list(object({
        name         = string
        node_count   = number
        vm_size      = string
        vm_set_type  = string
        os_disk_type = optional(string, "Managed")
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

variable "tags" {
  description = "Optional tags to apply to all resources"
  type        = map(string)
  default     = {}
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

variable "route_table_config_list" {
  description = "List of route table configurations"
  type = list(object({
    name                          = string
    bgp_route_propagation_enabled = optional(bool, true)
    routes = list(object({
      name                         = string
      address_prefix               = optional(string, null)
      address_prefix_publicip_name = optional(string, null)
      next_hop_type                = string
      next_hop_in_ip_address       = optional(string, null)
      next_hop_firewall_name       = optional(string, null)
    }))
    subnet_associations = list(object({
      subnet_name = string
    }))
  }))
  default = []
}


variable "firewall_config_list" {
  description = "List of firewall configurations"
  type = list(object({
    name                  = string
    network_role          = optional(string)
    subnet_name           = optional(string)
    public_ip_names       = optional(list(string), [])
    sku_name              = optional(string, "AZFW_VNet")
    sku_tier              = optional(string, "Standard")
    firewall_policy_id    = optional(string)
    threat_intel_mode     = optional(string, "Alert")
    dns_proxy_enabled     = optional(bool, false)
    dns_servers           = optional(list(string))
    ip_configuration_name = optional(string, "firewall-ipconfig")
    nat_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = optional(string, "Dnat")
      rules = list(object({
        name                  = string
        source_addresses      = optional(list(string))
        source_ip_groups      = optional(list(string))
        destination_ports     = list(string)
        destination_addresses = list(string)
        translated_address    = string
        translated_port       = string
        protocols             = list(string)
      }))
    })))
    network_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = string
      rules = list(object({
        name                  = string
        source_addresses      = optional(list(string))
        source_ip_groups      = optional(list(string))
        destination_ports     = list(string)
        destination_addresses = optional(list(string))
        destination_fqdns     = optional(list(string))
        destination_ip_groups = optional(list(string))
        protocols             = list(string)
      }))
    })))
    application_rule_collections = optional(list(object({
      name     = string
      priority = number
      action   = string
      rules = list(object({
        name             = string
        source_addresses = optional(list(string))
        source_ip_groups = optional(list(string))
        target_fqdns     = optional(list(string))
        fqdn_tags        = optional(list(string))
        protocols = optional(list(object({
          port = string
          type = string
        })))
      }))
    })))
  }))
  default = []
}

variable "dns_zones" {
  description = "List of DNS zones to create"
  type = list(object({
    name = string
  }))
  default = []
}

variable "key_vault_config_list" {
  description = "List of Key Vault configurations for AKS KMS encryption. Each configuration specifies a Key Vault and its encryption keys to be created."
  type = list(object({
    name = string # Key Vault name
    keys = list(object({
      key_name = string # Encryption key name
    }))
  }))
  default = []

  validation {
    condition = alltrue([
      for config in var.key_vault_config_list : (
        length(config.name) >= 3 &&
        length(config.name) <= 20 &&
        length(config.keys) >= 1
      )
    ])
    error_message = "Each Key Vault config must have name 3-20 characters (total 24 after adding 4-char random suffix), and at least one key must be defined."
  }
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
    sku_tier     = string
    support_plan = optional(string, "KubernetesOfficial")
    default_node_pool = object({
      name                         = string
      subnet_name                  = optional(string)
      node_count                   = number
      vm_size                      = string
      os_sku                       = optional(string)
      os_disk_type                 = optional(string)
      os_disk_size_gb              = optional(number, null)
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
      os_type              = optional(string)
      os_sku               = optional(string)
      os_disk_type         = optional(string)
      os_disk_size_gb      = optional(number, null)
      max_pods             = optional(number)
      ultra_ssd_enabled    = optional(bool, false)
      zones                = optional(list(string), [])
      node_taints          = optional(list(string), [])
      node_labels          = optional(map(string), {})
      min_count            = optional(number, null)
      max_count            = optional(number, null)
      auto_scaling_enabled = optional(bool, false)
      priority             = optional(string, "Regular")
      eviction_policy      = optional(string, null)
      spot_max_price       = optional(number, null)
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
    web_app_routing = optional(object({
      dns_zone_names = list(string)
    }), null)
    kms_config = optional(object({
      key_name       = string
      key_vault_name = string
      network_access = optional(string, "Public")
    }), null)
    # Disk Encryption Set configuration for OS disk encryption with Customer-Managed Keys
    disk_encryption_set_name = optional(string, null) # Name of the Disk Encryption Set to use for OS disk encryption
  }))
  default = []
}

variable "vm_config_list" {
  description = "Configuration for virtual machines"
  type = list(object({
    # Basic VM configuration
    role           = string
    name           = string
    vm_size        = optional(string, "Standard_D4s_v3")
    admin_username = optional(string, "azureuser")

    # Network configuration - use NIC name from network module
    nic_name = string

    # AKS integration (optional)
    aks_name = optional(string, null)

    # OS disk configuration
    os_disk = optional(object({
      caching              = optional(string, "ReadWrite")
      storage_account_type = optional(string, "Standard_LRS")
      disk_size_gb         = optional(number, 64)
    }), {})

    # Image configuration
    image = optional(object({
      publisher = optional(string, "Canonical")
      offer     = optional(string, "ubuntu-24_04-lts")
      sku       = optional(string, "server")
      version   = optional(string, "latest")
    }), {})

    # NSG configuration
    nsg = optional(object({
      enabled = optional(bool, false)
      rules = optional(list(object({
        name                       = string
        priority                   = number
        direction                  = optional(string, "Inbound")
        access                     = optional(string, "Allow")
        protocol                   = optional(string, "Tcp")
        source_port_range          = optional(string, "*")
        destination_port_range     = string
        source_address_prefix      = optional(string, "*")
        destination_address_prefix = optional(string, "*")
      })), [])
    }), {})

    # Cloud-init template file name in templates/ folder
    cloud_init_template = optional(string, "cloud-init.tpl")

    # VM-specific tags (merged with global tags)
    vm_tags = optional(map(string), {})
  }))
  default = []
}

variable "aks_cli_config_list" {
  type = list(object({
    role     = string
    aks_name = string
    sku_tier = string

    managed_identity_name             = optional(string, null)
    subnet_name                       = optional(string, null)
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
        optional_parameters = optional(list(object({
          name  = string
          value = string
        })), [])
    })), [])
    optional_parameters = optional(list(object({
      name  = string
      value = string
    })), [])
    kms_config = optional(object({
      key_name       = string
      key_vault_name = string
      network_access = optional(string, "Public")
    }), null)
    dry_run = optional(bool, false) # If true, only print the command without executing it. Useful for testing.
    # Disk Encryption Set configuration for OS disk encryption with Customer-Managed Keys
    disk_encryption_set_name = optional(string, null) # Name of the Disk Encryption Set to use for OS disk encryption
  }))
  default = []
}

variable "arm_endpoint" {
  description = "Custom Azure Resource Manager endpoint URL for the AzAPI provider"
  type        = string
  default     = "https://management.azure.com"
}

variable "azapi_config_list" {
  description = "List of AKS cluster configurations to create via Azure REST API (AzAPI provider)"
  type = list(object({
    role        = string
    aks_name    = string
    dns_prefix  = string
    api_version = optional(string, "2026-01-02-preview")

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
  }))
  default = []
}

variable "disk_encryption_set_config_list" {
  description = "List of Disk Encryption Set configurations for encrypting AKS OS/data disks with Customer-Managed Keys. Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys"
  type = list(object({
    name            = string                                              # Name of the Disk Encryption Set
    key_vault_name  = string                                              # Name of the Key Vault containing the encryption key
    key_name        = string                                              # Name of the encryption key in the Key Vault
    encryption_type = optional(string, "EncryptionAtRestWithCustomerKey") # Type of encryption
    # Supported values:
    # - EncryptionAtRestWithCustomerKey (default): Disk is encrypted with customer-managed key
    # - EncryptionAtRestWithPlatformAndCustomerKeys: Double encryption (platform + customer key)
    # - ConfidentialVmEncryptedWithCustomerKey: For confidential VMs
    auto_key_rotation_enabled = optional(bool, false) # Enable automatic key rotation
  }))
  default = []

  validation {
    condition = alltrue([
      for config in var.disk_encryption_set_config_list : (
        length(config.name) >= 1 &&
        length(config.name) <= 80 &&
        length(config.key_vault_name) >= 1 &&
        length(config.key_name) >= 1
      )
    ])
    error_message = "Each Disk Encryption Set config must have name 1-80 characters, and key_vault_name and key_name must be specified."
  }
}

