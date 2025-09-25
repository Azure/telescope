scenario_type  = "perf-eval"
scenario_name  = "security-perf"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "cas"
    aks_name                      = "cas"
    dns_prefix                    = "cas"
    subnet_name                   = "aks-network"
    sku_tier                      = "standard"
    kubernetes_version            = "1.33"
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
        name       = "scalepool1"
        node_count = 1
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "ssh-access"
            value = "disabled"
          },
          {
            name  = "min-count"
            value = 1
          },
          {
            name  = "max-count"
            value = 501
          },
          {
            name  = "max-pods"
            value = 110
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = ""
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
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "pod-cidr"
        value = "10.0.0.0/9"
      },
      {
        name  = "service-cidr"
        value = "192.168.0.0/11"
      },
      {
        name  = "dns-service-ip"
        value = "192.168.0.10"
      },
      {
        name  = "ssh-access"
        value = "disabled"
      }
    ]
  }
]
