scenario_type  = "perf-eval"
scenario_name  = "csi-autoscale-5k"
deletion_delay = "10h"
owner          = "storage"

aks_config_list = [
  {
    role        = "cas"
    aks_name    = "csi-autoscale-5k"
    dns_prefix  = "csiscale"
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
      vm_size                      = "Standard_D8s_v6"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "systemtmp"
    }
    extra_node_pool = [
      {
        name                 = "csipool1"
        node_count           = 0
        min_count            = 0
        max_count            = 10
        auto_scaling_enabled = true
        vm_size              = "Standard_D2ds_v4"
        max_pods             = 30
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    kubernetes_version = "1.36"
    auto_scaler_profile = {
      scale_down_delay_after_add     = "5m"
      scale_down_delay_after_failure = "2m"
      scale_down_unneeded            = "5m"
      scale_down_unready             = "10m"
      scan_interval                  = "20s"
      max_unready_percentage         = 100
      skip_nodes_with_local_storage  = false
      empty_bulk_delete_max          = "1000"
      max_graceful_termination_sec   = "60"
      max_node_provisioning_time     = "30m"
      max_unready_nodes              = 5000
    }
  }
]
