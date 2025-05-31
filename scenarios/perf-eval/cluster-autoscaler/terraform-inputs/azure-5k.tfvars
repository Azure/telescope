scenario_type  = "perf-eval"
scenario_name  = "cluster-autoscaler"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "cas"
    aks_name    = "cas-5k"
    dns_prefix  = "cas-5k"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.128.0.0/11"
    }
    default_node_pool = {
      name                         = "system"
      node_count                   = 5
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D8_v5"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool1"
        node_count           = 1
        min_count            = 1
        max_count            = 995
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool2"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool3"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool4"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      },
      {
        name                 = "userpool5"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    kubernetes_version = "1.31"
    auto_scaler_profile = {
      scale_down_delay_after_add     = "1m"
      scale_down_delay_after_failure = "1m"
      scale_down_unneeded            = "1m"
      scale_down_unready             = "5m"
      scan_interval                  = "20s"
      max_unready_percentage         = 90
      skip_nodes_with_local_storage  = false
      empty_bulk_delete_max          = "1000"
      max_graceful_termination_sec   = "30"
    }
  }
]
