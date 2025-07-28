scenario_type  = "perf-eval"
scenario_name  = "auto-cluster-pod-startup"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "auto-cluster-pod-startup"
    sku_tier                      = "Standard"
    use_aks_preview_cli_extension = true
    grant_rbac_permissions        = true
    optional_parameters = [
      {
        name  = "sku"
        value = "automatic" # Enable AKS Automatic
      },
      {
        name  = "zones"
        value = "1 2 3" # Must add all zones for AKS Automatic
      }
    ]
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16s_v3"
        os_disk_type         = "Managed"
        node_labels          = { "prometheus" = "true" }
      }
    ]
  }
]