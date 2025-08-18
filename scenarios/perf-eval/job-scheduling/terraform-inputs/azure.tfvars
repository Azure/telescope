scenario_type  = "perf-eval"
scenario_name  = "job-scheduling"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                  = "client"
    aks_name              = "job-scheduling"
    sku_tier              = "standard"
    kubernetes_version    = "1.33"
    use_aks_preview_private_build = true
    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D8_v3"
    }
    extra_node_pool = [
      {
        name       = "kwokpool"
        node_count = 1
        vm_size    = "Standard_D64_v3"
        optional_parameters = [
          {
            name  = "labels"
            value = "kwok=true"
          },
          {
            name  = "node-taints"
            value = "kwok=true:NoSchedule"
          },
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
        name = "custom-configuration"
        value = "./custom-configuration.json"
      }
    ]
  }
]
