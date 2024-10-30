scenario_type  = "perf-eval"
scenario_name  = "cas-c4n10p100"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "cas"
    aks_name    = "cas"
    dns_prefix  = "cas"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D8_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool"
        node_count           = 0
        min_count            = 0
        max_count            = 10
        auto_scaling_enabled = true
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    kubernetes_version = "1.31"
    auto_scaler_profile = {
      scale_down_delay_after_add = "0m"
      scale_down_unneeded        = "0m"
    }
  }
]