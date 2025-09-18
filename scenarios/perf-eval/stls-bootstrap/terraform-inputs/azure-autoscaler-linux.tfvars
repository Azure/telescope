scenario_type  = "perf-eval"
scenario_name  = "stls-perf-autoscale-linux"
deletion_delay = "2h"
owner          = "aks"

# Network configuration for the autoscaler cluster
network_config_list = [
  {
    role               = "cas"
    vnet_name          = "stls-autoscaler-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "stls-autoscaler-subnet"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

# NOTE: Converting from aks_config_list to aks_cli_config_list
# LIMITATION: auto_scaler_profile cannot be configured via CLI
# The autoscaler profile settings will use AKS defaults:
# - scale_down_delay_after_add: 10m (instead of 1m)
# - scale_down_delay_after_failure: 3m (instead of 1m) 
# - scale_down_unneeded: 10m (instead of 1m)
# - scale_down_unready: 20m (instead of 5m)
# - scan_interval: 10s (instead of 20s)
# - max_unready_percentage: 45 (instead of 90)
# - skip_nodes_with_local_storage: true (instead of false)
# - empty_bulk_delete_max: 10 (instead of 1000)
# - max_graceful_termination_sec: 600 (instead of 30)
aks_cli_config_list = [
  {
    role     = "cas"
    aks_name = "stls-autoscaler"
    sku_tier = "Standard"
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    subnet_name = "stls-autoscaler-subnet"
    kubernetes_version = "1.33"
    optional_parameters = [
      {
        name  = "dns-name-prefix"
        value = "stls-autoscaler"
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
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      },
      {
        name  = "node-osdisk-type"
        value = "Managed"
      }
    ]
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8ds_v5"
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 1
        vm_size    = "Standard_D4ds_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = "true"
          },
          {
            name  = "min-count"
            value = "1"
          },
          {
            name  = "max-count"
            value = "11"
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      }
    ]
  }
]