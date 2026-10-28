scenario_type  = "perf-eval"
scenario_name  = "agent-sandbox-H8"
deletion_delay = "6h"
owner          = "aks"

azapi_config_list = [
  {
    role               = "client"
    aks_name           = "agent-sandbox-H8"
    dns_prefix         = "agent-sandbox-H8"
    kubernetes_version = "1.36.0"
    api_version        = "2026-01-02-preview"

    # The agent-sandbox controller (up to 12 CPU), KWOK and the load generator run on this pool.
    default_node_pool = {
      name    = "systempool1"
      count   = 4
      vm_size = "Standard_D16s_v5"
    }

    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }

    control_plane_scaling_profile = {
      scaling_size = "H8"
    }
  }
]
