scenario_type  = "perf-eval"
scenario_name  = "cnl-azurecni-overlay-cilium"
deletion_delay = "20h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "slo"
    aks_name           = "telescope-acns-scale-test"
    kubernetes_version = "1.33"
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
        value = "192.168.0.0/16"
      },
      {
        name  = "enable-acns"
        value = ""
      },
      {
        name  = "network-dataplane"
        value = "cilium"
      },
      {
        name  = "zones"
        value = "1 2 3"
      }
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 5
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
      zones                = ["1", "2", "3"]
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        zones                = ["1", "2", "3"]
        optional_parameters = [
          {
            name  = "labels"
            value = "prometheus=true"
          }
        ]
      },
      {
        name                 = "traffic"
        node_count           = 1000
        auto_scaling_enabled = false
        max_pods             = 250
        vm_size              = "Standard_D4_v3"
        zones                = ["1", "2", "3"]
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          }
        ]
      }
    ]
  }
]
