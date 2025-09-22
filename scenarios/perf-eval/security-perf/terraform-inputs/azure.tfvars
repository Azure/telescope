scenario_type  = "perf-eval"
scenario_name  = "security-perf"
deletion_delay = "6h"
owner          = "aks"

aks_cli_config_list = [
  {
    role       = "cas"
    aks_name   = "cas"
    dns_prefix  = "cas"
    subnet_name = "aks-network"
    sku_tier              = "standard"
    kubernetes_version    = "1.33"
    use_aks_preview_cli_extension = true

    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/DisableSSHPreview"
    ]

    default_node_pool = {
      name                         = "system"
      node_count                   = 5
      vm_size                      = "Standard_D4_v5"
    }
   extra_node_pool = [
      {
        name       = "scalepool1",
        node_count = 1,
        vm_size    = "Standard_D2ds_v4",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = true
          },
          {
            name  = "min-count"
            value = 1
          },
          {
            name  = "max-count"
            value = 2
          },
          {
        name  = "max-pods"
        value = 5
          },
          {
        name  = "labels"
        value = "cas=dedicated"
          }
        ]
      },    
      {
        name       = "scalepool2",
        node_count = 0,
        vm_size    = "Standard_D2ds_v4",
        optional_parameters = [
          {
        name       = "scalepool1",
        node_count = 1,
        vm_size    = "Standard_D2ds_v4",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = true
          },
          {
            name  = "min-count"
            value = 0
          },
          {
            name  = "max-count"
            value = 1
          },
          {
        name  = "max-pods"
        value = 5
          },
          {
        name  = "labels"
        value = "cas=dedicated"
          }
        ]
      },
       {
        name       = "scalepool3",
        node_count = 0,
        vm_size    = "Standard_D2ds_v4",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = true
          },
          {
            name  = "min-count"
            value = 0
          },
          {
            name  = "max-count"
            value = 1
          },
          {
        name  = "max-pods"
        value = 5
          },
          {
        name  = "labels"
        value = "cas=dedicated"
          }
        ]
      },
     {
        name       = "scalepool4",
        node_count = 0,
        vm_size    = "Standard_D2ds_v4",
        optional_parameters = [
          {
            name  = "sshAccess"
            value = "disabled"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = true
          },
          {
            name  = "min-count"
            value = 0
          },
          {
            name  = "max-count"
            value = 1
          },
          {
        name  = "max-pods"
        value = 5
          },
          {
        name  = "labels"
        value = "cas=dedicated"
          }
        ]
      }
     ]
    }
]
