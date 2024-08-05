scenario_type  = "perf-eval"
scenario_name  = "k8s-cluster-crud"
deletion_delay = "20h"
aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "vms-pool"
    sku_tier                      = "standard"
    use_aks_preview_cli_extension = true
    default_node_pool             = null
  }
]
