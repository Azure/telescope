scenario_type  = "perf-eval"
scenario_name  = "nsl-cilium"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "network"
    vnet_name          = "nsl-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "nsl-subnet"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "client"
    aks_name    = "nsl-cilium"
    dns_prefix  = "nsl"
    subnet_name = "nsl-vnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      network_dataplane   = "cilium"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 1
      vm_size                      = "Standard_D4ds_v5"
      os_disk_type                 = "Ephemeral"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool"
        node_count           = 1
        auto_scaling_enabled = true
        min_count            = 1
        max_count            = 2
        vm_size              = "Standard_D4ds_v5"
        os_disk_type         = "Ephemeral"
        node_labels          = { "node-startup-latency" = "true" }
      }
    ]
    kubernetes_version = "1.33"
  }
]
