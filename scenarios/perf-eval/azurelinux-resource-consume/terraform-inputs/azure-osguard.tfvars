scenario_type  = "perf-eval"
scenario_name  = "osguard-resource-consume"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role     = "client"
    aks_name = "cri-resource-consume"
    sku_tier = "standard"
    optional_parameters = [
      {
        name = "dns-name-prefix"
        value = "cri"
      },
      {
        name = "network-plugin"
        value = "azure"
      },
      {
        name = "network-plugin-mode"
        value = "overlay"
      },
      {
        name = "pod-cidr"
        value = "10.0.0.0/9"
      },
      {
        name = "enable-fips-image",
        value = ""
      },
      {
        name = "enable-secure-boot",
        value = ""
      },
      {
        name = "enable-vtpm",
        value = ""
      },
      {
        name = "service-cidr"
        value = "192.168.0.0/16"
      },
      {
        name = "dns-service-ip"
        value = "192.168.0.10"
      },
      {
        name = "node-osdisk-type"
        value = "Managed"
      },
      {
        name = "os-sku"
        value = "AzureLinuxOSGuard"
      },
      {
        name = "nodepool-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D16_v4"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D16_v4"
        optional_parameters = [
          {
            name = "labels"
            value = "prometheus=true"
          },
          {
            name = "enable-fips-image",
            value = ""
          },
          {
            name = "enable-secure-boot",
            value = ""
          },
          {
            name = "enable-vtpm",
            value = ""
          },
          {
            name = "os-sku"
            value = "AzureLinuxOSGuard"
          }
        ]
      },
      {
        name       = "userpool0"
        node_count = 10
        vm_size    = "Standard_D16s_v6"
        optional_parameters = [
          {
            name = "labels"
            value = "cri-resource-consume=true"
          },
          {
            name = "node-taints"
            value = "cri-resource-consume=true:NoSchedule"
          },
          {
            name = "enable-fips-image",
            value = ""
          },
          {
            name = "enable-secure-boot",
            value = ""
          },
          {
            name = "enable-vtpm",
            value = ""
          },
          {
            name = "os-sku"
            value = "AzureLinuxOSGuard"
          }
        ]
      }
    ]
    kubernetes_version = "1.32"
  }
]