scenario_type  = "perf-eval"
scenario_name  = "security-perf"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "cas"
    aks_name                      = "cas"
    sku_tier                      = "standard"
    kubernetes_version            = "1.33"
    use_aks_preview_cli_extension = true

    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/DisableSSHPreview"
    ]

    default_node_pool = {
      name                         = "system"
      node_count                   = 5
      vm_size                      = "Standard_D4_v5"
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
        name  = "ssh-access"
        value = "disabled"
      }
    ]
  }
]
