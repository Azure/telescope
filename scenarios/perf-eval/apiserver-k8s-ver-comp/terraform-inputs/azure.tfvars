scenario_type  = "perf-eval"
scenario_name  = "apiserver-k8s-ver-comp"
deletion_delay = "20h"
owner          = "aks"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "k8s-ver-comp"
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
        node_count = 10
        vm_size    = "Standard_D4s_v3"
      },
      {
        name       = "runner"
        node_count = 3
        vm_size    = "Standard_D16s_v3"
      }
    ]
  }
]