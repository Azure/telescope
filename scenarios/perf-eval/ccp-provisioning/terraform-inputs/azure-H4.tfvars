scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H4"
deletion_delay = "2h"
owner          = "aks"


azapi_config_list = [
  {
    role               = "client"
    aks_name           = "ccp-provisioning-H4"
    dns_prefix         = "ccp-provisioning-H4"
    kubernetes_version = "1.33.0"
    api_version        = "2026-01-02-preview"

    default_node_pool = {
      name    = "systempool1"
      count   = 3
      vm_size = "Standard_D2s_v3"
    }

    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }

    control_plane_scaling_profile = {
      scaling_size = "H4"
    }
  }
]