scenario_type  = "perf-eval"
scenario_name  = "apiserver-cm100"
deletion_delay = "10h"
owner          = "aks"

aks_config_list = [
  {
    role               = "client"
    aks_name           = "configmaps100"
    dns_prefix         = "kperf"
    subnet_name        = "aks-network"
    sku_tier           = "Standard"
    kubernetes_version = "1.32"

    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D2s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "runner"
        node_count = 3
        vm_size    = "Standard_D16s_v3"
      }
    ]
  }
]
