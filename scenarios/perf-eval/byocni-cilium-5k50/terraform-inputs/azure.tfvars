scenario_type  = "perf-eval"
scenario_name  = "byocni-cilium-5k50"
deletion_delay = "24h"
owner          = "aks"

network_config_list = [
  {
    role               = "slo"
    vnet_name          = "slo-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "slo-subnet-1"
        address_prefix = "10.0.0.0/12"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                          = "slo"
    aks_name                      = "slo-byocni-5k50"
    sku_tier                      = "Standard"
    subnet_name                   = "slo-subnet-1"
    use_aks_preview_cli_extension = true
    kubernetes_version            = "1.33"

    optional_parameters = [
      {
        name  = "generate-ssh-keys"
        value = ""
      },
      {
        name  = "network-plugin"
        value = "none"
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
        name  = "max-pods"
        value = "110"
      },
      {
        name  = "enable-addons"
        value = "monitoring"
      },
      {
        name  = "load-balancer-managed-outbound-ip-count"
        value = "20"
      }
    ]

    default_node_pool = {
      name                 = "system"
      node_count           = 5
      auto_scaling_enabled = false
      vm_size              = "Standard_D8s_v4"
    }

    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D32s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "prometheus=true"
          }
        ]
      },
      {
        name                 = "userpool1"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D4s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                 = "userpool2"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D4s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                 = "userpool3"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D4s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                 = "userpool4"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D4s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      },
      {
        name                 = "userpool5"
        node_count           = 0
        min_count            = 0
        max_count            = 1000
        auto_scaling_enabled = true
        vm_size              = "Standard_D4s_v4"
        optional_parameters = [
          {
            name  = "labels"
            value = "slo=true scale-test=true"
          },
          {
            name  = "node-taints"
            value = "slo=true:NoSchedule"
          }
        ]
      }
    ]
  }
]
