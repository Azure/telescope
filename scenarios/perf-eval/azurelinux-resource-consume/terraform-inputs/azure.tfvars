scenario_type  = "perf-eval"
scenario_name  = "azurelinux-resource-consume"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "cri-resource-consume"
    dns_prefix  = "cl2"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D16s_v3"
      os_disk_type                 = "Managed"
      os_sku                       = "AzureLinux"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16_v3"
        os_sku               = "AzureLinux"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name        = "userpool0"
        node_count  = 10
        vm_size     = "Standard_D16s_v3"
        os_sku      = "AzureLinux"
        node_taints = ["cri-resource-consume=true:NoSchedule"]
        node_labels = { "cri-resource-consume" = "true" }
      }
    ]
  }
]
