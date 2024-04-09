scenario_type  = "perf-eval"
scenario_name  = "disk-attach-dettach"
deletion_delay = "2h"

  public_ips = {
        {
            name = "disk-attach-detach-pip"
        }
  }

network_config_list = [
  {
    role               = "client"
    vnet_name          = "disk-attach-detach-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "disk-attach-detach-subnet"
      address_prefix = "10.1.1.0/24"
    }]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations = [
    {
        nic_name              = "disk-attac-detach-nic"
        subnet_name           = "disk-attach-detach-subnet"
        ip_configuration_name = "disk-attach-detach-config"
        public_ip_name        = "disk-attach-detach-pip"
    }
  ]
    nsr_rules = []
}
]

data_disk_config_list = [{
  disk_name = "disk-attach-dettach-storage-disk1"
  zone      = 1
  },
  {
    disk_name = "disk-attach-dettach-storage-disk2"
    zone      = 1
}]

vm_config_list = [{
  role           = "vm-attach-dettach"
  vm_name        = "vm-1"
  nic_name = "vm-attach-dettach-nic"
  subnet_name    = "disk-attach-detach-subnet"
  admin_username = "ubuntu"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
}]
