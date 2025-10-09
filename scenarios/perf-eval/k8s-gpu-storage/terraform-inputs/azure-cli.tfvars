scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-storage"
deletion_delay = "240h"
owner          = "aks"
aks_cli_config_list = [
  {
    role               = "storage"
    aks_name           = "gpu-storage"
    sku_tier           = "standard"
    kubernetes_version = "1.33"
    default_node_pool = {
      name       = "default"
      node_count = 2
      # vm_size    = "Standard_D16ds_v4"
      vm_size = "Standard_NC4as_T4_v3"
    }
    extra_node_pool = [
      {
        name       = "user",
        node_count = 2,
        # vm_size    = "Standard_NC24ads_A100_v4",
        vm_size = "Standard_ND96asr_v4",
        optional_parameters = [
          {
            name  = "node-osdisk-type"
            value = "Ephemeral"
          },
          {
            name  = "os-sku"
            value = "Ubuntu2404"
          },
          {
            name  = "node-taints"
            value = "fio-dedicated=true:NoExecute,fio-dedicated=true:NoSchedule"
          },
          {
            name  = "labels"
            value = "fio-dedicated=true"
          },
          {
            name  = "gpu-driver"
            value = "none"
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
        name  = "os-sku"
        value = "Ubuntu2404"
      },
      {
        name  = "node-osdisk-type"
        value = "Ephemeral"
      }
    ]
  }
]
