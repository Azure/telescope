scenario_type  = "perf-eval"
scenario_name  = "apiserver-vn100pod10k"
deletion_delay = "20h"
owner          = "aks"

aks_cli_config_list = [
  {
    role     = "client"
    aks_name = "vn100-p10k"
    sku_tier = "standard"

    aks_custom_headers = [
      "ControlPlaneUnderlay=hcp-underlay-eastus2-cx-382"
    ]

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
