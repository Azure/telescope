scenario_type  = "perf-eval"
scenario_name  = "stls-bootstrap"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "cas"
    aks_name           = "stls-bootstrap-windows"
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
        name       = "winpool0"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
        optional_parameters = [
          {
            name  = "os-type"
            value = "Windows"
          }
        ]
      },
      {
        name       = "winpool1"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
        optional_parameters = [
          {
            name  = "os-type"
            value = "Windows"
          }
        ]
      },
      {
        name       = "winpool2"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
        optional_parameters = [
          {
            name  = "os-type"
            value = "Windows"
          }
        ]
      },
      {
        name       = "winpool3"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
        optional_parameters = [
          {
            name  = "os-type"
            value = "Windows"
          }
        ]
      },
      {
        name       = "winpool4"
        node_count = 2
        vm_size    = "Standard_D2ds_v5"
        node_labels = {
          cas = "dedicated"
        }
        optional_parameters = [
          {
            name  = "os-type"
            value = "Windows"
          }
        ]
      }
    ]
  }
]