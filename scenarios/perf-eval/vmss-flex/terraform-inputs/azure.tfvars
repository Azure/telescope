scenario_type  = "perf-eval"
scenario_name  = "vmss-flex-scale"
deletion_delay = "2h"
network_config_list = [
  {
    role                        = "network"
    vnet_name                   = "vmss-flex-scale-vnet"
    vnet_address_space          = "10.2.0.0/16"
    network_security_group_name = "vmss-flex-scale-nsg"
    subnet = [{
      name           = "vmss-flex-scale-subnet"
      address_prefix = "10.2.1.0/24"
    }]
    nic_public_ip_associations = []
    nsr_rules                  = []
  }
]