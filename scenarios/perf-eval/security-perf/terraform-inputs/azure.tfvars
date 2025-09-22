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
            name  = "enableAutoscaling"
            value = true
          },
          {
            name  = "nodeCountMin"
            value = 1
          },
          {
            name  = "nodeCountMax"
            value = 2
          },
          {
        name  = "maxPods"
        value = 5
          },
          {
        name  = "nodepool-labels"
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
            value = 1
          },
          {
        name  = "maxPods"
        value = 5
          },
          {
        name  = "nodepool-labels"
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
            name  = "enableAutoscaling"
            value = true
          },
          {
            name  = "nodeCountMin"
            value = 0
          },
          {
            name  = "nodeCountMax"
            value = 1
          },
          {
        name  = "maxPods"
        value = 5
          },
          {
        name  = "nodepool-labels"
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
            name  = "enableAutoscaling"
            value = true
          },
          {
            name  = "nodeCountMin"
            value = 0
          },
          {
            name  = "nodeCountMax"
            value = 1
          },
          {
        name  = "maxPods"
        value = 5
          },
          {
        name  = "nodepool-labels"
        value = "cas=dedicated"
          }
        ]
      }
  }
]
