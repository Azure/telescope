scenario_type  = "perf-eval"
scenario_name  = "k8s-cluster-crud-machine"
deletion_delay = "4h"
owner          = "aks"
aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "mchapi"
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
      }
    ]
  }
]
