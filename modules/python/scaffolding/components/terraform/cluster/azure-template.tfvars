basic_cluster_list = [
  {
    role        = "client"
    aks_name    = "vn10-p100"
    dns_prefix  = "kperf"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
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

cas_cluster_list = [
  {
    role        = "cas"
    aks_name    = "cas"
    dns_prefix  = "cas"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D8_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool"
        node_count           = 0
        min_count            = 0
        max_count            = 10
        auto_scaling_enabled = true
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    kubernetes_version = "1.31"
    auto_scaler_profile = {
      scale_down_delay_after_add = "0m"
      scale_down_unneeded        = "0m"
    }
  }
]


nap_cluster_list = [
  {
    role     = "nap"
    aks_name = "nap-c4n10p100"
    sku_tier = "standard"

    default_node_pool = {
      name       = "system"
      node_count = 3
      vm_size    = "Standard_D4_v3"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "node-provisioning-mode"
        value = "Auto"
      },
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "network-dataplane"
        value = "cilium"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
  }
]

