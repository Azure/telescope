scenario_type  = "perf-eval"
scenario_name  = "cluster-autoscaler"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "cas"
    vnet_name          = "aks-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "aks-network"
        address_prefix = "10.0.0.0/16"
      },
      {
        name           = "apiserver-subnet"
        address_prefix = "10.1.0.0/24"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = []

aks_cli_config_list = [
  {
    role                   = "cas"
    aks_name               = "cas"
    sku_tier               = "Standard"
    managed_identity_name  = "cas-managed-identity"
    subnet_name            = "aks-network"
    kubernetes_version     = "1.33"
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D4_v5"
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 1
        vm_size    = "Standard_D4_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
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
    optional_parameters = [
      {
        name  = "dns-name-prefix"
        value = "cas"
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
        name  = "service-cidr"
        value = "10.96.0.0/12"
      },
      {
        name  = "dns-service-ip"
        value = "10.96.0.10"
      },
      {
        name  = "cluster-autoscaler-profile"
        value = "scan-interval=20s,scale-down-delay-after-add=1m,scale-down-delay-after-failure=1m,scale-down-unneeded-time=1m,scale-down-unready-time=5m,max-graceful-termination-sec=30,max-empty-bulk-delete=1000,skip-nodes-with-local-storage=false,max-total-unready-percentage=90"
      }
    ]
  }
]
