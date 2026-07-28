scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-cluster-crud"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "gpu"
    aks_name                      = "gpu-cluster"
    sku_tier                      = "standard"
    kubernetes_version            = "1.33"
    use_aks_preview_cli_extension = true
    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D16s_v4"
    }

    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      }
    ]
  }
]
