scenario_type  = "perf-eval"
scenario_name  = "cluster-autoscaler"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "cas"
    aks_name           = "cas-vms"
    sku_tier           = "Standard"
    subnet_name        = "aks-network"
    kubernetes_version = "1.33"
    optional_parameters = [
      {
        name  = "dns-name-prefix"
        value = "cas-vms"
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
        name  = "node-osdisk-type"
        value = "Managed"
      },
      {
        name  = "cluster-autoscaler-profile"
        value = "scan-interval=20s,scale-down-delay-after-add=1m,scale-down-delay-after-failure=1m,scale-down-unneeded-time=1m,scale-down-unready-time=5m,max-graceful-termination-sec=30,max-empty-bulk-delete=1000,skip-nodes-with-local-storage=false,max-total-unready-percentage=90"
      }
    ]
    default_node_pool = {
      name        = "system"
      node_count  = 5
      vm_size     = "Standard_D4ds_v5"
      vm_set_type = "VirtualMachines"
    }
    extra_node_pool = [
      {
        name        = "userpool"
        node_count  = 1
        vm_size     = "Standard_D4ds_v5"
        vm_set_type = "VirtualMachines"
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
  }
]
