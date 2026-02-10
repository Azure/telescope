scenario_type  = "perf-eval"
scenario_name  = "image-pull-n10"
deletion_delay = "1h"
owner          = "acr"

network_config_list = [
  {
    role               = "client"
    vnet_name          = "imgpull-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "imgpull-subnet-1"
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
    aks_name    = "img-pull-1000-5gb"
    dns_prefix  = "imgpull"
    subnet_name = "imgpull-vnet"
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
      vm_size                      = "Standard_D4ds_v5"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D4ds_v5"
        os_disk_type         = "Managed"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool"
        node_count           = 1000
        auto_scaling_enabled = false
        vm_size              = "Standard_D4ds_v5"
        os_disk_type         = "Managed"
        node_labels          = { "cri-resource-consume" = "true" }
      }
    ]
  }
]
