scenario_type  = "perf-eval"
scenario_name  = "pls-single-vm"
deletion_delay = "2h"

public_ip_config_list = [
    {
        name = "vm-pip"
    }
]

network_config_list = [
    {
        role = "network"
        vnet_name = "vnet"
        vnet_address_space = "10.0.0.0/16"
        subnet = [{
            name = "subnet"
            address_prefix = "10.0.2.0/24"
            pls_network_policies_enabled = false
        }]
        network_security_group_name = "nsg"
        nic_public_ip_associations = [
            {
                nic_name = "vm_nic"
                subnet_name = "subnet"
                ip_configuration_name = "vm-ipconfig"
                public_ip_name = "vm-pip"
            }
        ]
        nsr_rules = [{
      name                       = "nsr-ssh"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "2222"
      source_address_prefix      = "*"
      destination_address_prefix = "*"
      },
      {
        name                       = "nsr-tcp"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20001-20001"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-udp"
        priority                   = 102
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Udp"
        source_port_range          = "*"
        destination_port_range     = "20002-20002"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
    }
]

vm_config_list =[{
    role = "client"
    vm_name = "vm"
    nic_name = "vm_nic"
    admin_username = "ubuntu"
    zone = "1"
    source_image_reference = {
        publisher = "Canonical"
        offer = "0001-com-ubuntu-server-focal"
        sku = "20_04-lts"
        version = "latest"
    }
    create_vm_extension = true
}]

storage_account_name_prefix = "plssinglevm"

pe_config = {
  pe_name = "private-endpoint"
  pe_subnet_name = "same-subnet"

  psc_config = {
    psc_name = "private-service-connection"
  }
}