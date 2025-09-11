scenario_type  = "perf-eval"
scenario_name  = "cluster-automatic"
deletion_delay = "2h"
owner          = "aks"
aks_cli_config_list = [
  {
    role                          = "automatic"
    aks_name                      = "automatic"
    sku_tier                      = "Standard"
    use_aks_preview_cli_extension = true
    grant_rbac_permissions        = true
    optional_parameters = [
      {
        name  = "sku"
        value = "automatic" # Enable automatic
      },
      {
        name  = "zones"
        value = "1 2 3" # Must add all zones since: Managed cluster 'Automatic' SKU should enable 'AvailabilityZones' feature with recommended values
      }
    ]
  }
]