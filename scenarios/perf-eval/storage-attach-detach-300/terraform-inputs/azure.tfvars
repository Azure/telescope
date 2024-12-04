scenario_type  = "perf-eval"
scenario_name  = "storage-attach-detach-300"
deletion_delay = "6h"
owner          = "aks"
network_config_list = [
  {
    role               = "network"
    vnet_name          = "aks-network-vnet"
    vnet_address_space = "125.0.0.0/8"
    subnet = [{
      name           = "aks-network-300"
      address_prefix = "125.0.0.0/14"
    }]
    network_security_group_name = "aks-network-nsg"
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]
aks_config_list = [
  {
    role       = "client"
    aks_name   = "perfevala300"
    dns_prefix = "attach"
    sku_tier   = "Free"
    network_profile = {
      network_plugin = "kubenet"
      pod_cidr       = "125.4.0.0/14"
    }
    default_node_pool = {
      name                         = "default"
      subnet_name                  = "aks-network-300"
      node_count                   = 3
      vm_size                      = "Standard_D2s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name        = "user"
        subnet_name = "aks-network-300"
        node_count  = 300
        vm_size     = "Standard_D2s_v3"
        node_labels = { "csi" = "true" }
      }
    ]
    kubernetes_version = "1.30"
  }
]
