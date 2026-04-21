scenario_type  = "perf-eval"
scenario_name  = "vmagent-loadtest"
deletion_delay = "6h"
owner          = "aks"

network_config_list = [
  {
    role               = "cp"
    vnet_name          = "vmagent-cp-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "cp-subnet"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "dp"
    vnet_name          = "vmagent-dp-vnet"
    vnet_address_space = "10.128.0.0/9"
    subnet = [
      {
        name           = "dp-subnet"
        address_prefix = "10.128.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "cp"
    aks_name    = "vmagent-cp"
    dns_prefix  = "vmagent-cp"
    subnet_name = "cp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.64.0.0/12"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      vm_size                      = "Standard_D4_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = []
    kubernetes_version = "1.30"
  },
  {
    role        = "dp"
    aks_name    = "vmagent-dp"
    dns_prefix  = "vmagent-dp"
    subnet_name = "dp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.192.0.0/12"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "nodepool1"
      node_count                   = 10
      vm_size                      = "Standard_D2_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = []
    kubernetes_version = "1.30"
  }
]
