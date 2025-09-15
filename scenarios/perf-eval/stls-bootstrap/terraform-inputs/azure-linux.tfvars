scenario_type  = "perf-eval"
scenario_name  = "stls-bootstrap"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "cas"
    aks_name           = "stls-bootstrap-linux"
    sku_tier           = "Standard"
    kubernetes_version = "1.33"
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D2ds_v5"
      node_labels = {
        cas = "dedicated"
      }
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
      },
      {
        name       = "userpool1"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
      },
      {
        name       = "userpool2"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
      },
      {
        name       = "userpool3"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
      },
      {
        name       = "userpool4"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
      }
    ]
  }
]
