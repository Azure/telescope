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

aks_config_list = [
  {
    role        = "cni-static-block"
    aks_name    = "cni-static-block"
    dns_prefix  = "cni-static-block"
    subnet_name = "podsubnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D8_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        max_pods             = 110
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool0"
        node_count           = 0
        min_count            = 0
        max_count            = 500
        auto_scaling_enabled = true
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
        node_taints          = ["slo=true:NoSchedule"]
        node_labels          = { "slo" = "true" }
      },
      {
        name                 = "userpool1"
        node_count           = 0
        min_count            = 0
        max_count            = 500
        auto_scaling_enabled = true
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
        node_taints          = ["slo=true:NoSchedule"]
        node_labels          = { "slo" = "true" }
      }
    ]
    kubernetes_version = "1.32"
  }
]
