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
    role               = "client"
    vnet_name          = "client-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "client-subnet"
      address_prefix = "10.1.1.0/24"
    }]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations = [{
      nic_name              = "client-nic"
      subnet_name           = "client-subnet"
      ip_configuration_name = "client-ipconfig"
      public_ip_name        = "client-pip"
    }]
    nsr_rules = []
}]

data_disk_config_list = [{
  disk_name = "vm-attach-dettach-storage-disk1"
  zone      = 1
  },
  {
    disk_name = "vm-attach-dettach-storage-disk2"
    zone      = 1
}]

vm_config_list = [{
  role           = "vm-attach-dettach"
  vm_name        = "vm-1"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
}]
