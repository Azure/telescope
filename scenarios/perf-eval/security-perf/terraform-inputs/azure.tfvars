scenario_type  = "perf-eval"
scenario_name  = "security-perf"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "cas"
    aks_name                      = "cas"
    dns_prefix                    = "cas"
    subnet_name                   = "aks-network"
    sku_tier                      = "standard"
    kubernetes_version            = "1.33"
    use_aks_preview_cli_extension = true
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.128.0.0/11"
      service_cidr         = "10.2.0.0/16"
      dns_service_ip       = "10.2.0.10"
    }

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

    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/DisableSSHPreview"
    ]

    default_node_pool = {
      name                         = "system"
      node_count                   = 5
      vm_size                      = "Standard_D4_v5"
      optional_parameters = [
        {
          name  = "enable-cluster-autoscaler"
          value = ""
        },
        {
            name  = "ssh-access"
            value = "disabled"
        },
        {
          name  = "node-osdisk-type"
          value = "Managed"
        }
      ]
    }

    extra_node_pool = [
      {
        name       = "scalepool1"
        node_count = 1
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "ssh-access"
            value = "disabled"
          },
          {
            name  = "min-count"
            value = 1
          },
          {
            name  = "max-count"
            value = 1000
          },
          {
            name  = "max-pods"
            value = 110
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          }
        ]
      }
    ]
  }
]
