scenario_type  = "perf-eval"
scenario_name  = "security-perf"
deletion_delay = "6h"
owner          = "aks"

aks_cli_config_list = [
  {
    role       = "client"
    aks_name   = "security-perf"
    sku_tier              = "standard"
    kubernetes_version    = "1.33"
    use_aks_preview_cli_extension = true
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D16_v5"
    }
   extra_node_pool = [
      {
        name       = "scalepool1",
        node_count = 1,
        vm_size    = "Standard_D16_v5",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enableAutoscaling"
            value = true
          },
          {
            name  = "nodeCountMin"
            value = 1
          },
          {
            name  = "nodeCountMax"
            value = 499
          },
      {
        name       = "scalepool2",
        node_count = 0,
        vm_size    = "Standard_D16_v5",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enableAutoscaling"
            value = true
          },
          {
            name  = "nodeCountMin"
            value = 0
          },
          {
            name  = "nodeCountMax"
            value = 499
          },
        ]
      }
  }
]
