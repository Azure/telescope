scenario_name  = "k8s-mongodb"
scenario_type  = "perf-eval"
deletion_delay = "20h"
aks_config_list = [
  {
    role        = "client"
    aks_name    = "mongodb-aks"
    dns_prefix  = "mongodb"
    subnet_name = "aks-network"
    sku_tier    = "Free"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D16s_v4"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "server"
        node_count = 2
        vm_size    = "Standard_D32s_v3"
        zones      = ["1"]
      },
      {
        name       = "client"
        node_count = 2
        vm_size    = "Standard_L8s_v3"
        zones      = ["1"]
      }
    ]
  }
]
