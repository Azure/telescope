scenario_type  = "perf-eval"
scenario_name  = "k8s-node-stress"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "k8s-node-stress"
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=EnableSelfContainedVHD"
    ]
    sku_tier           = "standard"
    kubernetes_version = "1.34"
    default_node_pool = {
      name       = "default"
      node_count = 1
      vm_size    = "Standard_D8_v5"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D8_v5"
        optional_parameters = [
          {
            name = "labels"
            value = "prometheus=true"
          }
        ]
      },
      {
        name       = "userpool1",
        node_count = 1,
        vm_size    = "Standard_D8_v5",
        optional_parameters = [
          {
            name  = "os-sku"
            value = "Ubuntu2204"
          },
          {
            name  = "kubelet-config"
            value = "./linux-kubelet-config.yaml"
          },
          {
            name  = "node-taints"
            value = "cri-resource-consume=true:NoSchedule,cri-resource-consume=true:NoExecute"
          },
          {
            name  = "labels"
            value = "cri-resource-consume=true"
          },
          {
            name  = "aks-custom-headers"
            value = "AKSHTTPCustomFeatures=EnableSelfContainedVHD"
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
        value = "192.168.0.0/16"
      },
      {
        name  = "dns-service-ip"
        value = "192.168.0.10"
      },
      {
        name  = "os-sku"
        value = "Ubuntu2204"
      }
    ]
  }
]
