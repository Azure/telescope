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
    subnet_name                   = "podsubnet"
    sku_tier                      = "standard"
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
            name  = "pod_ip_allocation_mode"
            value = "StaticBlock"
          },
          {
            name  = "auto_scaling_enabled"
            value = "false"
          }
        ]
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        vm_size              = "Standard_D64_v3"
        optional_parameters = [
          {
            name  = "pod_ip_allocation_mode"
            value = "StaticBlock"
          },
          {
            name  = "max_pods"
            value = "110"
          },
          {
            name  = "node_labels"
            value = "prometheus=true"
          },
          {
            name  = "auto_scaling_enabled"
            value = "false"
          }
        ]
      },
      {
        name                        = "userpool0"
        node_count                  = 0
        vm_size                     = "Standard_D4_v3"
        optional_parameters = [
          {
            name  = "pod_ip_allocation_mode"
            value = "StaticBlock"
          },
          {
            name  = "max_pods"
            value = "110"
          },
          {
            name  = "node_labels"
            value = "slo=true"
          },
          {
            name  = "auto_scaling_enabled"
            value = "true"
          },
          {
            name  = "min_count"
            value = "0"
          },
          {
            name  = "max_count"
            value = "500"
          },
          {
            name  = "max_count"
            value = "true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                          = "userpool1"
        node_count                    = 0
        vm_size                       = "Standard_D4_v3"
        optional_parameters = [
          {
            name  = "pod_ip_allocation_mode"
            value = "StaticBlock"
          },
          {
            name  = "max_pods"
            value = "110"
          },
          {
            name  = "node_labels"
            value = "slo=true"
          },
          {
            name  = "auto_scaling_enabled"
            value = "true"
          },
          {
            name  = "min_count"
            value = "0"
          },
          {
            name  = "max_count"
            value = "500"
          },
          {
            name  = "max_count"
            value = "true"
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
