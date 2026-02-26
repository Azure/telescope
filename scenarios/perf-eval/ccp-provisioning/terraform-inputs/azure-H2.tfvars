scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H2"
deletion_delay = "2h"
owner          = "aks"

aks_rest_config_list = [
  {
    role                       = "client"
    aks_name                   = "ccp-provisioning-H2"
    sku_tier                   = "Standard"
    sku_name                   = "Base"
    api_version                = "2026-01-02-preview"
    control_plane_scaling_size = "H2"
    kubernetes_version         = "1.33"
    network_plugin             = "azure"
    network_plugin_mode        = "overlay"
    default_node_pool = {
      name       = "systempool"
      mode       = "System"
      node_count = 3
      vm_size    = "Standard_D2s_v5"
      os_type    = "Linux"
    }
  }
]
