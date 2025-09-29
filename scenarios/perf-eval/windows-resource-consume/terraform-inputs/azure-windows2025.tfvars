scenario_type  = "perf-eval"
scenario_name  = "windows-resource-consume"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "cri-resource-consume"
    sku_tier           = "standard"
    kubernetes_version = "1.32"
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D16ds_v4"
    }
    extra_node_pool = [
      {
        name       = "prompool",
        node_count = 1,
        vm_size    = "Standard_D16ds_v4",
        optional_parameters = [
          {
            name  = "labels"
            value = "prometheus=true"
          },
          {
            name  = "os-sku"
            value = "Ubuntu"
          },
          {
            name  = "node-osdisk-type "
            value = "Ephemeral"
          }
        ]
      },
      {
        name       = "user",
        node_count = 10,
        vm_size    = "Standard_D16ds_v4",
        optional_parameters = [
          {
            name  = "node-osdisk-type"
            value = "Ephemeral"
          },
          {
            name  = "os-type"
            value = "Windows"
          },
          {
            name  = "os-sku"
            value = "Windows2025"
          },
          {
            name  = "node-taints"
            value = "cri-resource-consume=true:NoSchedule"
          },
          {
            name  = "labels"
            value = "cri-resource-consume=true"
          },
          {
            name  = "enable-fips-image"
            value = ""
          }
        ]
      }
    ]
    optional_parameters = [
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
        value = "10.0.0.0/9"
      },
      {
        name  = "service-cidr"
        value = "192.168.0.0/16"
      },
      {
        name  = "dns-service-ip"
        value = "192.168.0.10"
      },
      {
        name  = "node-osdisk-type "
        value = "Ephemeral"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
  }
]
