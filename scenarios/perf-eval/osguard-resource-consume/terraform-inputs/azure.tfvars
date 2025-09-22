scenario_type  = "perf-eval"
scenario_name  = "osguard-resource-consume"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "client"
    vnet_name          = "cri-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "cri-subnet-1"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role     = "client"
    aks_name = "cri-resource-consume"
    aks_custom_headers = ["AKSHTTPCustomFeatures=Microsoft.ContainerService/UseCustomizedOSImage,OSImageSubscriptionID=b8f169b2-5b23-444a-ae4b-19a31b5e3652,OSImageResourceGroup=hebebermlinuxguard,OSImageGallery=hebebermlinuxguard,OSImageName=LGAKS,OSImageVersion=0.250821.0,OSSKU=AzureLinux"]
    sku_tier = "standard"
    subnet_name = "cri-vnet"
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
        value = "AzureLinux"
      },
      {
        name = "nodepool-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D16s_v3"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D16s_v3"
        optional_parameters = [
          {
            name = "labels"
            value = "prometheus=true"
          },
          {
            name = "os-sku"
            value = "AzureLinux"
          }
        ]
      },
      {
        name       = "userpool0"
        node_count = 10
        vm_size    = "Standard_D16s_v3"
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
            name = "os-sku"
            value = "AzureLinux"
          }
        ]
      }
    ]
    kubernetes_version = "1.31"
  }
]