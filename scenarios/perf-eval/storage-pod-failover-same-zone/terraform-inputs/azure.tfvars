scenario_type  = "perf-eval"
scenario_name  = "storage-pod-failover-same-zone"
deletion_delay = "6h"
network_config_list = [
  {
    role               = "network"
    vnet_name          = "aks-network-vnet"
    vnet_address_space = "125.0.0.0/8"
    subnet = [{
      name           = "aks-network"
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
    aks_name   = "perfevalpodfailoversz"
    dns_prefix = "attach"
    sku_tier   = "Free"
    network_profile = {
      network_plugin = "kubenet"
      pod_cidr       = "125.4.0.0/14"
    }
    default_node_pool = {
      name                         = "default"
      subnet_name                  = "aks-network"
      node_count                   = 3
      vm_size                      = "Standard_D2s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name        = "user"
        subnet_name = "aks-network"
        node_count  = 6
        vm_size     = "Standard_D2s_v3"
        zones       = ["1", "2"]
      }
    ]
  }
]

loadbalancer_config_list = []

vm_config_list = []

vmss_config_list = []

nic_backend_pool_association_list = []
