scenario_type  = "perf-eval"
scenario_name  = "create-delete-vm"
deletion_delay = "2h"

network_config_list = [
  {
    role                        = "network"
    vnet_name                   = "create-delete-vm-vnet"
    vnet_address_space          = "10.2.0.0/16"
    network_security_group_name = "create-delete-vm-nsg"
    subnet = [{
      name           = "create-delete-vm-subnet"
      address_prefix = "10.2.1.0/24"
    }]
    nic_public_ip_associations = []
    nsr_rules                  = [
      {
        name                       = "nsr-ssh"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "22"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-rdp"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "3389"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]
