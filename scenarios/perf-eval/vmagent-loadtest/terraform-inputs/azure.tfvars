scenario_type  = "perf-eval"
scenario_name  = "vmagent-loadtest"
deletion_delay = "3h"
owner          = "aks"

aks_config_list = [
  {
    role        = "cp"
    aks_name    = "vmagent-cp"
    dns_prefix  = "vmagent-cp"
    subnet_name = "cp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D4_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = [
      {
        name                = "controlplane"
        node_count          = 3
        auto_scaling_enabled = false
        vm_size             = "Standard_D4_v3"
        os_disk_type        = "Managed"
        max_pods            = 250
      }
    ]
  },
  {
    role        = "dp"
    aks_name    = "vmagent-dp"
    dns_prefix  = "vmagent-dp"
    subnet_name = "dp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "172.16.0.0/12"
    }
    default_node_pool = {
      name                         = "nodepool1"
      node_count                   = 2
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D2_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = [
      {
        name                = "dataplane"
        node_count          = 1
        auto_scaling_enabled = false
        vm_size             = "Standard_D2_v3"
        os_disk_type        = "Managed"
        max_pods            = 250
      }
    ]
  }
]
