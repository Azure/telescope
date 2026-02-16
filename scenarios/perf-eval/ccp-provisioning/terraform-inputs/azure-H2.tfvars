scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H2"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "ccp-provisioning-H2"
    sku_tier           = "standard"
    aks_custom_headers = [
      "EtcdServersOverrides=hyperscale"
    ]
    kubernetes_version = "1.33"
    default_node_pool = {
      name       = "default"
      node_count = 1
      vm_size    = "Standard_D8s_v3"
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
