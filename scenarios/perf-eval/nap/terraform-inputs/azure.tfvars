scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "720h"
owner          = "aks"

aks_config_list = []

aks_cli_config_list = [
  {
    role               = "nap"
    aks_name           = "nap"
    sku_tier           = "standard"
    kubernetes_version = "1.31"
    default_node_pool = {
      name       = "system"
      node_count = 1
      vm_size    = "Standard_D8ds_v6"
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
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      },
      {
        name  = "enable-cost-analysis"
        value = ""
      }
    ]
  }
]
