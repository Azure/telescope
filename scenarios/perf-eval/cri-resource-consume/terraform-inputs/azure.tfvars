scenario_type  = "perf-eval"
scenario_name  = "cri-resource-consume"
deletion_delay = "240h"
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

aks_config_list = [
  {
    role        = "client"
    aks_name    = "cri-resource-consume"
    dns_prefix  = "cri"
    subnet_name = "cri-vnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.0.0.0/9"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D16ds_v4"
      os_disk_type                 = "Ephemeral"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16ds_v4"
        os_disk_type         = "Ephemeral"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool0"
        node_count           = 10
        auto_scaling_enabled = false
        vm_size              = "Standard_D16ds_v4"
        os_disk_type         = "Ephemeral"
        node_taints          = ["cri-resource-consume=true:NoSchedule", "cri-resource-consume=true:NoExecute"]
        node_labels          = { "cri-resource-consume" = "true" }
      }
    ]
    kubernetes_version = "1.32"
  }
]
