scenario_type  = "perf-eval"
scenario_name  = "apiserver-vn100pod3k-28days"
deletion_delay = "720h"
aks_config_list = [
  {
    role        = "client"
    aks_name    = "apiservervn100pod3k28day"
    dns_prefix  = "kperf"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
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
