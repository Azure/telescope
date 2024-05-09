scenario_type  = "perf-eval"
scenario_name  = "disk-attach-dettach"
deletion_delay = "2h"

public_ip_config_list = [{
  name = "disk-attach-detach-pip"
  }
]

network_config_list = [
  {
    role               = "disk-attach-detach-net-role"
    vnet_name          = "disk-attach-detach-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "disk-attach-detach-subnet"
      address_prefix = "10.1.1.0/24"
    }]
    network_security_group_name = "disk-attach-detach-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "single-disk-attach-detach-nic"
        subnet_name           = "disk-attach-detach-subnet"
        ip_configuration_name = "disk-attach-detach-config"
        public_ip_name        = "disk-attach-detach-pip"
      }
    ]
    nsr_rules = []
  }
]

data_disk_config = {
  name_prefix = "disk-attach-detach-storage-disk"
  zone        = 1
}

vm_config_list = [{
  info_column_name = "cloud_info.vm_info"
  role             = "disk-attach-detach-target-vm-role"
  vm_name          = "single-attach-detach-vm"
  nic_name         = "single-disk-attach-detach-nic"
  admin_username   = "ubuntu"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
}]
