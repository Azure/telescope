scenario_type  = "perf-eval"
scenario_name  = "apiserver-vn100pod3k"
deletion_delay = "20h"
owner          = "aks"

aks_config_list = [
  {
    role               = "client"
    aks_name           = "vn100-p3k"
    dns_prefix         = "kperf"
    subnet_name        = "aks-network"
    sku_tier           = "Standard"
    kubernetes_version = "1.31"

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
        name       = "virtualnodes"
        node_count = 5
        vm_size    = "Standard_D8s_v3"
      },
      {
        name       = "runner"
        node_count = 3
        vm_size    = "Standard_D16s_v3"
      }
    ]
  }
]
