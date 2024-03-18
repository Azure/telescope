scenario_type  = "perf-eval"
scenario_name  = "create-delete-vm"
deletion_delay = "2h"
network_config_list = [
  {
    role                        = "network"
    vnet_name                   = "create-delete-vm-vnet"
    vnet_address_space          = "10.2.0.0/16"
    network_security_group_name = "create-delete-vm-nsg"
    subnet                      = []
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]
