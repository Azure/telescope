scenario_type  = "perf-eval"
scenario_name  = "nap-c2n2kp2k"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = []

aks_cli_config_list = [
  {
    role               = "nap"
    aks_name           = "nap-c2n2kp2k"
    sku_tier           = "standard"
    kubernetes_version = "1.31"
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8s_v4"
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
        value = "10.240.0.0/12"
      },
    ]
  }
]
