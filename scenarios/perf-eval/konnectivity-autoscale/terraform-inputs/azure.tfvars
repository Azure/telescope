scenario_type  = "perf-eval"
scenario_name  = "konnectivity-autoscale"
deletion_delay = "240h"
owner          = "aks"

network_config_list = [
  {
    role               = "konnectivity"
    vnet_name          = "cri-autoscale-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "cri-autoscale-subnet-1"
        address_prefix = "10.0.0.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "konnectivity"
    aks_name    = "konnectivity-autoscale"
    dns_prefix  = "cl2"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D16s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16_v3"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool"
        node_count           = 1
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D16s_v3"
        max_pods             = 110
      }
    ]
    kubernetes_version = "1.30"
  }
]
