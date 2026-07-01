scenario_type  = "perf-eval"
scenario_name  = "vmagent-loadtest"
deletion_delay = "10h"
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
      # 100.64.0.0/10 (CGNAT space): avoids the default AKS service_cidr
      # (10.0.0.0/16), the 10.224.0.0/12 VNet, and the AKS-reserved ranges
      # (172.30/16, 172.31/16, 169.254/16, 192.0.2/24, 224.0.0.0/4).
      # 172.16.0.0/12 was rejected after AKS tightened pod-CIDR overlap
      # validation. /10 gives 16k /24 node blocks — ample for 5K+ nodes.
      # Same choice as the cnl-azurecni-overlay-cilium scenario.
      pod_cidr            = "100.64.0.0/10"
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
