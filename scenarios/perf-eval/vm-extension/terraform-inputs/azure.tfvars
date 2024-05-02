scenario_type  = "perf-eval"
scenario_name  = "create-delete-vm"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "ingress-pip"
  }
]
network_config_list = [
  {
    role                        = "network"
    vnet_name                   = "vm-extension-vnet"
    vnet_address_space          = "10.2.0.0/16"
    network_security_group_name = "vm-extension-nsg"
    subnet = [{
      name           = "vm-extension-vm-subnet"
      address_prefix = "10.2.1.0/24"
    }]
    nic_public_ip_associations = [
      {
        nic_name              = "vm-extension-nic"
        subnet_name           = "vm-extension-vm-subnet"
        ip_configuration_name = "vm-extension-ipconfig"
        public_ip_name        = "ingress-pip"
      }
    ]
    nsr_rules = []
  }
]

vm_config_list = [
  {
    info_column_name = "cloud_info.vm_info"
    role             = "vm-role"
    vm_name          = "vm-extension"
    nic_name         = "vm-extension-nic"
    admin_username   = "ubuntu"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  }
]