scenario_type  = "perf-eval"
scenario_name  = "image-pull-n1000"
deletion_delay = "3h"
owner          = "acr"

public_ip_config_list = [
  {
    name  = "imgpull-nat-gateway-pip"
    count = 5
  }
]

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
    # Spread node outbound traffic over multiple IPs; many nodes behind a single IP get rate-limited (HTTP 429) by packages.microsoft.com
    nat_gateway_associations = [{
      nat_gateway_name = "imgpull-nat-gateway"
      subnet_names     = ["imgpull-subnet-1"]
      public_ip_names  = ["imgpull-nat-gateway-pip-1", "imgpull-nat-gateway-pip-2", "imgpull-nat-gateway-pip-3", "imgpull-nat-gateway-pip-4", "imgpull-nat-gateway-pip-5"]
    }]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "client"
    aks_name    = "img-pull-500"
    dns_prefix  = "imgpull"
    subnet_name = "imgpull-subnet-1"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      outbound_type       = "userAssignedNATGateway"
      pod_cidr            = "10.128.0.0/9"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      subnet_name                  = "imgpull-subnet-1"
      node_count                   = 3
      vm_size                      = "Standard_D4ds_v5"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        subnet_name          = "imgpull-subnet-1"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        os_disk_type         = "Managed"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool"
        subnet_name          = "imgpull-subnet-1"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D4ds_v5"
        os_disk_type         = "Managed"
        node_labels          = { "cri-resource-consume" = "true" }
      }
    ]
  }
]
