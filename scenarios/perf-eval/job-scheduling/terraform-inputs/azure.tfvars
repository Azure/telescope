scenario_type  = "perf-eval"
scenario_name  = "job-scheduling"
deletion_delay = "1h"
owner          = "aks"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "job-scheduling"
    dns_prefix  = "job-scheduling"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D8_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
      node_labels                  = { "default" = "true" }
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        max_pods             = 110
        node_labels          = { "prometheus" = "true" }
      },
      {
        name        = "kwokpool"
        node_count  = 1
        auto_scaling_enabled = false
        vm_size     = "Standard_D64_v3"
        max_pods             = 110
        node_labels = { "kwok" = "true" }
      }
    ]
    kubernetes_version = "1.33"
  }
]
