scenario_type  = "perf-eval"
scenario_name  = "hobo-automatic"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "automatic"
    aks_name                      = "automatic"
    sku_tier                      = "Standard"
    use_aks_preview_cli_extension = true
    optional_parameters = [
      {
        name  = "sku"
        value = "automatic"
      },
      {
        name  = "enable-hosted-system"
        value = ""
      },
      {
        name  = "zones"
        value = "1 2 3"
      }
    ]
  }
]