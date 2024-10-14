scenario_type  = "perf-eval"
scenario_name  = "slo-n100p5000"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "slo"
    aks_name    = "slo"
    dns_prefix  = "cl2"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 4
      vm_size                      = "Standard_D64_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name        = "userpool0"
        node_count  = 100
        vm_size     = "Standard_D4_v3"
        node_taints = ["slo=true:NoSchedule"]
      }
    ]
    kubernetes_version = "1.30"
  }
]
