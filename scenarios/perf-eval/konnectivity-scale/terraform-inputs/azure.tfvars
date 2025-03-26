scenario_type  = "perf-eval"
scenario_name  = "konnectivity-scale"
deletion_delay = "6h"
owner          = "aks"

network_config_list = [
  {
    role               = "client"
    vnet_name          = "cri-autoscale-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "cri-autoscale-subnet-1"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "client"
    aks_name    = "konnectivity-scale"
    dns_prefix  = "cl2"
    subnet_name = "cri-autoscale-subnet-1"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.128.0.0/9"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D16_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D32_v3"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool0"
        node_count           = 1
        min_count            = 0
        max_count            = 500
        auto_scaling_enabled = true
        vm_size              = "Standard_D2_v3"
        max_pods             = 110
        node_labels          = { "cri-resource-consume" = "true" }
      },
      {
        name                 = "userpool1"
        node_count           = 0
        min_count            = 0
        max_count            = 501
        auto_scaling_enabled = true
        vm_size              = "Standard_D2_v3"
        max_pods             = 110
        node_labels          = { "cri-resource-consume" = "true" }
      }
    ]
    kubernetes_version = "1.30"
  }
]
