scenario_type  = "perf-eval"
scenario_name  = "stls-bootstrap"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "stls-testing"
    aks_name                      = "stls-bootstrap"
    sku_tier                      = "Standard"
    kubernetes_version            = "1.33"
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D2_v3"
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 200
        vm_size    = "Standard_D2_v3"
      },
      {
        name       = "userpool1"
        node_count = 200
        vm_size    = "Standard_D2_v3"
      },
      {
        name       = "userpool2"
        node_count = 200
        vm_size    = "Standard_D2_v3"
      },
      {
        name       = "userpool3"
        node_count = 200
        vm_size    = "Standard_D2_v3"
      },
      {
        name       = "userpool4"
        node_count = 200
        vm_size    = "Standard_D2_v3"
      }
    ]
  }
]
