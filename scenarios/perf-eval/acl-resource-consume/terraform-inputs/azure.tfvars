scenario_type  = "perf-eval"
scenario_name  = "acl-resource-consume"
deletion_delay = "2h"
owner          = "aks"

# This scenario intentionally uses the AKS CLI Terraform path instead of the
# azurerm AKS resource path so it can pass ACL-specific AKS CLI options such as
# --os-sku AzureContainerLinux.
aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "acl-resource-consume"
    sku_tier                      = "standard"
    kubernetes_version            = "1.35"
    use_aks_preview_cli_extension = true
    aks_custom_headers            = []
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D16_v5"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D16_v5"
        optional_parameters = [
          {
            name  = "labels"
            value = "prometheus=true"
          },
          {
            name  = "os-sku"
            value = "AzureContainerLinux"
          },
          {
            name  = "enable-secure-boot"
            value = ""
          },
          {
            name  = "enable-vtpm"
            value = ""
          },
          {
            name  = "tags"
            value = "AzSecPackAutoConfigReady=true"
          }
        ]
      },
      {
        name       = "userpool0"
        node_count = 10
        vm_size    = "Standard_D16ds_v6"
        optional_parameters = [
          {
            name  = "node-osdisk-type"
            value = "Ephemeral"
          },
          {
            name  = "os-sku"
            value = "AzureContainerLinux"
          },
          {
            name  = "enable-secure-boot"
            value = ""
          },
          {
            name  = "enable-vtpm"
            value = ""
          },
          {
            name  = "tags"
            value = "AzSecPackAutoConfigReady=true"
          },
          {
            name  = "node-taints"
            value = "cri-resource-consume=true:NoSchedule,cri-resource-consume=true:NoExecute"
          },
          {
            name  = "labels"
            value = "cri-resource-consume=true"
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
        value = "AzureContainerLinux"
      },
      {
        name  = "enable-secure-boot"
        value = ""
      },
      {
        name  = "enable-vtpm"
        value = ""
      },
      {
        name  = "nodepool-tags"
        value = "AzSecPackAutoConfigReady=true"
      },
      {
        name  = "node-os-upgrade-channel"
        value = "None"
      }
    ]
  }
]
