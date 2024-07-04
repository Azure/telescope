scenario_name  = "vn-boot-latency"
scenario_type  = "perf-eval"
deletion_delay = "24h"

network_config_list = [
  {
    role               = "vperf"
    vnet_name          = "myVnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "myAKSSubnet"
        address_prefix = "10.240.0.0/16"
      },
      {
        name           = "myVirtualNodeSubnet"
        address_prefix = "10.241.0.0/16"

        delegations = [{
          name                       = "delegation"
          service_delegation_name    = "Microsoft.ContainerInstance/containerGroups"
          service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]        
        }]
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_config_list = [
  {
    role        = "vperf"
    aks_name    = "vn-boot-latency"
    dns_prefix  = "vnboot"
    subnet_name = "myAKSSubnet"
    sku_tier    = "Free"
    network_profile = {
      network_plugin      = "azure"
      pod_cidr            = "172.16.0.0/16" # Change this to a non-overlapping range
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D2_v3" # Updated VM size
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "user"
        node_count = 1
        vm_size    = "Standard_D16_v3" # Updated VM size
      }
    ]
    role_assignment_list = ["Network Contributor"]
  }
]
