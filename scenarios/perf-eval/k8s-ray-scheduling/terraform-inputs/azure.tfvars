scenario_type  = "perf-eval"
scenario_name  = "k8s-ray-scheduling"
deletion_delay = "120h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "ray"
    aks_name                      = "ray-scheduling"
    sku_tier                      = "Standard"
    kubernetes_version            = "1.34"
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D32ds_v4"
    }
    extra_node_pool = [
      {
        name       = "kwokpool"
        node_count = 15
        vm_size    = "Standard_D64ds_v6"
        optional_parameters = [
          {
            name  = "labels"
            value = "kwok=true"
          },
          {
            name  = "node-taints"
            value = "kwok=true:NoSchedule"
          },
          {
            name = "os-sku"
            value = "Ubuntu2404"
          }
        ]
      },
    ]
    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "os-sku"
        value = "Ubuntu2404"
      }
    ]
  }
]

