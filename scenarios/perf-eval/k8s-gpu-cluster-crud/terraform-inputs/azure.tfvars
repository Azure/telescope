scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-cluster-crud"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "gpu"
    aks_name                      = "gpu-aks-cluster"
    sku_tier                      = "standard"
    use_aks_preview_cli_extension = true
    default_node_pool             = null

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
        name  = "pod-cidr"
        value = "10.240.0.0/12"
      }
    ]
  }
]