owner          = "aks"
scenario_type  = "perf-eval"
scenario_name  = "konnectivity-monitoring"
deletion_delay = "2h"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "konnectivity-monitoring"
    dns_prefix  = "kperf"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D2s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
    }
    extra_node_pool = [
      {
        name       = "scalingpool"
        node_count = 5
        vm_size    = "Standard_D8s_v3"
      }
    ]
  }
]
