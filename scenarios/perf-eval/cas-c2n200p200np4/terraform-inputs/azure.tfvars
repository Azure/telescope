scenario_type  = "perf-eval"
scenario_name  = "cas-c2n200p200np4"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "cas"
    aks_name    = "cas-c2n200p200np4"
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
      vm_size                      = "Standard_D4ds_v4"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool1"
        node_count           = 1
        min_count            = 1
        max_count            = 51
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool2"
        node_count           = 0
        min_count            = 0
        max_count            = 50
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool3"
        node_count           = 0
        min_count            = 0
        max_count            = 50
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool4"
        node_count           = 0
        min_count            = 0
        max_count            = 50
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    kubernetes_version = "1.34"
    auto_scaler_profile = {
      scale_down_delay_after_add     = "2m"
      scale_down_delay_after_failure = "1m"
      scale_down_unneeded            = "3m"
      scale_down_unready             = "5m"
      scan_interval                  = "20s"
      max_unready_percentage         = 100
      skip_nodes_with_local_storage  = false
      empty_bulk_delete_max          = "200"
      max_graceful_termination_sec   = "30"
      max_node_provisioning_time     = "15m"
      max_unready_nodes              = 195
    }
  }
]
