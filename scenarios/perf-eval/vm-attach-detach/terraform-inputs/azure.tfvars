scenario_type  = "perf-eval"
scenario_name  = "vm-attach-dettach"
deletion_delay = "2h"

public_ip_config_list = [
  {
    name = "client-pip"
  }
]

network_config_list = [
{
  role               = "server"
  vnet_name          = "server-vnet"
  vnet_address_space = "10.1.0.0/16"
  subnet = [{
    name           = "client-network"
    address_prefix = "10.1.1.0/24"
  }]
  network_security_group_name = "server-nsg"
  nic_public_ip_associations = [
    {
      nic_name              = "client-nic"
      subnet_name           = "client-network"
      ip_configuration_name = "client-ipconfig"
      public_ip_name        = "client-pip"
    }
  ]
  nsr_rules = [
  {
     name                       = "server-nsr-ssh"
     priority                   = 100
     direction                  = "Inbound"
     access                     = "Allow"
     protocol                   = "Tcp"
     source_port_range          = "*"
     destination_port_range     = "22"
     source_address_prefix      = "*"
     destination_address_prefix = "*"
  }]
}]

data_disk_config_list = [{
  disk_name    = "vm-attach-dettach-storage-disk1"
  zone         = 1
},
{
  disk_name    = "vm-attach-dettach-storage-disk2"
  zone         = 1
}]

vm_config_list = [{
    role           = "vm-attach-dettach"
    vm_name        = "vm-1"
    nic_name       = "client-nic"
    admin_username = "ubuntu"
    source_image_reference = {
        publisher = "Canonical"
        offer     = "0001-com-ubuntu-server-focal"
        sku       = "20_04-lts"
        version   = "latest"
    }
    create_vm_extension = false
}]
