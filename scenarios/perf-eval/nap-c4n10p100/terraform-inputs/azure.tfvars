scenario_type  = "perf-eval"
scenario_name  = "nap-c4n10p100"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = []

aks_cli_config_list = [
  {
    role     = "nap"
    aks_name = "nap-c4n10p100"
    sku_tier = "standard"

    default_node_pool = {
      name       = "system"
      node_count = 3
      vm_size    = "Standard_D4_v3"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "node-provisioning-mode"
        value = "Auto"
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
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "enable-addons"
        value = "azure-policy"
      }
    ]
  }
]
