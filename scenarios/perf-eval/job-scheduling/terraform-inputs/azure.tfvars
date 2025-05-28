scenario_type  = "perf-eval"
scenario_name  = "job-scheduling"
deletion_delay = "3h"
owner          = "aks"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "client"
    dns_prefix  = "client"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D2_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name        = "virtualnodes"
        node_count  = 3
        vm_size     = "Standard_D8_v3"
        node_taints = ["virtual=true:NoSchedule"]
        node_labels = { "virtual" = "true" }
      }
    ]
    kubernetes_version = "1.32"
  }
]
