scenario_type  = "perf-eval"
scenario_name  = "acns-azurecni-overlay"
deletion_delay = "20h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "acns"
    aks_name           = "telescope-acns-scale-test"
    sku_tier           = "standard"
    kubernetes_version = "1.32"
    sku_tier           = "Standard"

    optional_parameters = [
      {
        name  = "generate-ssh-keys"
        value = ""
      },
      {
        name  = "max-pods"
        value = "250"
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
        name  = "pod-cidr"
        value = "100.64.0.0/10"
      },
      {
        name  = "enable-acns"
        value = ""
      }
    ]

    default_node_pool = {
      name       = "default"
      node_count = 5
      auto_scaling_enabled = false
      vm_size    = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        auto_scaling_enabled = false
        vm_size    = "Standard_D64_v3"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name       = "traffic"
        node_count = 5
        auto_scaling_enabled = false
        max_pods   = 110
        vm_size    = "Standard_D4_v3"
        node_taints          = ["slo=true:NoSchedule"]
        node_labels          = { "slo" = "true" }
      }
    ]
  }
]
