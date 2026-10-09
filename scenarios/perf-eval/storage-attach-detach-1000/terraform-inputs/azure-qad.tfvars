scenario_type  = "perf-eval"
scenario_name  = "storage-attach-detach-1000"
deletion_delay = "6h"
owner          = "aks"

qad_config_list = [
  {
    role               = "client"
    aks_name           = "perfevalqad1000"
    dns_prefix         = "attachqad"
    api_version        = "2026-07-02-preview"
    kubernetes_version = "1.37.0"
    network_profile = {
      network_plugin = "kubenet"
      pod_cidr       = "125.4.0.0/14"
    }
    system_node_pool = {
      name     = "systempool"
      count    = 3
      vm_size  = "Standard_D2s_v3"
      os_type  = "Linux"
      mode     = "System"
    }
    user_node_pools = [
      {
        name        = "user"
        count       = 40
        vm_size     = "Standard_D16s_v3"
        os_type     = "Linux"
        mode        = "User"
        node_labels = { "csi" = "true" }
      }
    ]
  }
]
