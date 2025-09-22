scenario_type  = "perf-eval"
scenario_name  = "security-feature-perf"
deletion_delay = "6h"
owner          = "aks"

aks_cli_config_list = [
  {
    role       = "security"
    aks_name   = "security-feature-perf"
    sku_tier              = "standard"
    subnet_name           = "security-subnet"
    managed_identity_name = "security-identity"
    kubernetes_version    = "1.33"

    use_aks_preview_cli_extension = true
    use_aks_preview_private_build = true

    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/DisableSSHPreview",
    ]

    default_node_pool = {
      name                         = "default"
      node_count                   = 1000
      vm_size                      = "Standard_D2s_v3"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "ssh-access"
        value = "disabled"
      }
    ]
  }
]
