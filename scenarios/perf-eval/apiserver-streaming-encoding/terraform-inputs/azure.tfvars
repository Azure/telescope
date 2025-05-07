scenario_type  = "perf-eval"
scenario_name  = "apiserver-streaming-encoding"
deletion_delay = "3h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "vn100-p10k-streaming"
    sku_tier                      = "standard"
    kubernetes_version            = "1.31"
    use_aks_preview_private_build = true

    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D2s_v3"
    }
    extra_node_pool = [
      {
        name       = "virtualnodes"
        node_count = 5
        vm_size    = "Standard_D8s_v3"
      },
      {
        name       = "runner"
        node_count = 3
        vm_size    = "Standard_D16s_v3"
      }
    ]
  }
]
