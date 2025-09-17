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
    sku_tier = "standard"
    subnet_name = "cri-vnet"
    optional_parameters = [
      {
        name = "dns-name-prefix"
        value = "cri"
      },
#      {
#        name = "vnet-subnet-id"
#        value = "cri-vnet"
#      },
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
      # temporary_name_for_rotation = "defaulttmp"
    ]
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D16_v3"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D16_v3"
        optional_parameters = [
          {
            name = "labels"
            value = "prometheus=true"
          },
          {
            name = "os-sku"
            value = "AzureLinux"
          }
          # auto_scaling_enabled = false
        ]
      },
      {
        name       = "userpool0"
        node_count = 10
        vm_size    = "Standard_D16_v3"
        optional_parameters = [
          # auto_scaling_enabled = false
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