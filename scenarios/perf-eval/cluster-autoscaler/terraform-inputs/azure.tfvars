scenario_type  = "perf-eval"
scenario_name  = "cluster-auto-scaler"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "client"
    aks_name    = "aks-cluster-autoscaler"
    dns_prefix  = "kperf"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    auto_scaler_profile = {
      balance_similar_node_groups = true
      max_unready_nodes           = 0
      scan_interval               = "2s"
      new_pod_scale_up_delay      = "1m"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D4_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
      enable_auto_scaling          = true
      min_count                    = 3
      max_count                    = 5
    }
    extra_node_pool = [
      {
        name                = "virtualnodes"
        node_count          = 1
        vm_size             = "Standard_D4_v3"
        enable_auto_scaling = true
        min_count           = 1
        max_count           = 10
      }
     
    ]
  }
]

aks_cli_config_list = [
  {
    role     = "client"
    aks_name = "aks-cluster-NAP"
    sku_tier = "standard"

    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name       = "virtualnodes"
        node_count = 1
        vm_size    = "Standard_D4_v3"
      }     
    ]
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
      }
    ]
  }
]
