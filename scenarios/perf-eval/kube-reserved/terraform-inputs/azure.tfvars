scenario_type  = "perf-eval"
scenario_name  = "kube-reserved"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "kube-reserved"
    aks_name    = "kube-reserved"
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
      vm_size                      = "Standard_D16_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 3
        vm_size    = "Standard_D16_v3"
        max_pods   = 250
        node_taints = ["kube-reserved=true:NoSchedule"]
        node_labels = { "kube-reserved" = "true" }
      }
    ]
    kubernetes_version = "1.30"
  }
]
