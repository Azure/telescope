scenario_type  = "perf-eval"
scenario_name  = "apiserver-benchmark-virtualnodes100-pods3k"
deletion_delay = "20h"
aks_config_list = [
  {
    role           = "client"
    aks_name       = "virtualnodes100-pods3k"
    dns_prefix     = "kperf"
    subnet_name    = "aks-network"
    network_plugin = "azure"
    sku_tier       = "Standard"
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
