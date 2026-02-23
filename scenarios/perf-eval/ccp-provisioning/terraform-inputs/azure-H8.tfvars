scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H8"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "ccp-provisioning-H8"
    sku_tier           = "standard"
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/ControlPlaneScalingProfilePreview,EtcdServersOverrides=hyperscale"
    ]
    use_aks_preview_cli_extension = true
    use_aks_preview_private_build = true
    kubernetes_version = "1.33"
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D8s_v3"
    }
    optional_parameters = [
      {
        name  = "enable-hyperscale"
        value = ""
      },
      {
        name  = "hyperscale-size"
        value = "H8"
      },
      {
        name  = "uptime-sla"
        value = ""
      },
      {
        name  = "enable_aks_cli_preview_extension"
        value = ""
      },
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
