scenario_type  = "perf-eval"
scenario_name  = "image-pull-test"
deletion_delay = "2h"
owner          = "telescope"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "img-pull-10"
    dns_prefix  = "kperf"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "userpool0"
      node_count                   = 10
      vm_size                      = "Standard_D4s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "temp"
    }
    extra_node_pool = []
  }
]
