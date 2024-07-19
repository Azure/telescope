scenario_type  = "perf-eval"
scenario_name  = "vm-redeploy"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name  = "vm-redeploy-public-ip"
    count = 20
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "vm-redeploy-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "vm-redeploy-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = "vm-redeploy-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "vm-redeploy-nic"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip"
        count                 = 20
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

vm_config_list = [{
  role           = "vm-redeploy-role"
  vm_name        = "vm-redeploy"
  nic_name       = "vm-redeploy-nic"
  admin_username = "ubuntu"
  zone           = "1"
  count          = 20
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
}]