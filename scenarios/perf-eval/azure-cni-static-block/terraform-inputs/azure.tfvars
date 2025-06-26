scenario_type  = "perf-eval"
scenario_name  = "azure-cni-static-block"
deletion_delay = "12h"
owner          = "aks"

network_config_list = [
  {
    role               = "cni-static-block"
    vnet_name          = "cni-static-block-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "podsubnet"
        address_prefix = "10.40.0.0/13"
      },
      {
        name           = "nodesubnet"
        address_prefix = "10.240.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = []

aks_cli_config_list = [
  {
    role                          = "cni-static-block"
    aks_name                      = "cni-static-block"
    dns_prefix                    = "cni-static-block"
    sku_tier                      = "standard"
    subnet_name                   = "nodesubnet"
    node_subnet_name              = "nodesubnet"
    pod_subnet_name               = "podsubnet"
    pod_ip_allocation_mode        = "StaticBlock"
    kubernetes_version            = "1.32"
    use_aks_preview_private_build = true
    use_aks_preview_cli_extension = true
    network_profile = {
      network_plugin      = "azure"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      vm_size                      = "Standard_D8_v3"
      optional_parameters = [
          {
            name  = "pod-ip-allocation-mode"
            value = "StaticBlock"
          }
        ]
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 5
        vm_size              = "Standard_D64_v3"
        optional_parameters = [
          {
            name  = "pod-ip-allocation-mode"
            value = "StaticBlock"
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "prometheus=true"
          }
        ]
      },
      {
        name                        = "userpool0"
        node_count                  = 50
        vm_size                     = "Standard_D4_v3"
        optional_parameters = [
          {
            name  = "pod-ip-allocation-mode"
            value = "StaticBlock"
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "slo=true"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "800"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                          = "userpool1"
        node_count                    = 50
        vm_size                       = "Standard_D4_v3"
        optional_parameters = [
          {
            name  = "pod-ip-allocation-mode"
            value = "StaticBlock"
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "slo=true"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "800"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                          = "userpool2"
        node_count                    = 50
        vm_size                       = "Standard_D4_v3"
        optional_parameters = [
          {
            name  = "pod-ip-allocation-mode"
            value = "StaticBlock"
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "slo=true"
          },
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "800"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
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
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "service-cidr"
        value = "192.168.0.0/16"
      },
      {
        name  = "dns-service-ip"
        value = "192.168.0.10"
      }
    ]
  }
]
