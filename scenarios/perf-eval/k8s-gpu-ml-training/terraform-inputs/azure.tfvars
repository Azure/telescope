scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-ml-training"
deletion_delay = "24h"
owner          = "aks"
aks_cli_config_list = [
  {
    role                          = "gpu"
    aks_name                      = "gpu-ml-training"
    sku_tier                      = "Standard"
    kubernetes_version            = "1.32"
    use_aks_preview_cli_extension = true
    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D16_v3"
    }

    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      }
    ]

    extra_node_pool = [
      {
        name       = "user",
        node_count = 2,
        vm_size    = "Standard_ND96asr_v4",
        optional_parameters = [
          {
            name  = "node-osdisk-type"
            value = "Ephemeral"
          },
          {
            name  = "gpu-driver"
            value = "none"
          }
        ]
      }
    ]
  }
]
