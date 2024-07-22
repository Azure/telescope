scenario_type  = "perf-eval"
scenario_name  = "vm-extension"
deletion_delay = "2h"


public_ip_config_list = [
  {
    name  = "vm-extension-public-ip"
    count = 10
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "vm-extension-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "vm-extension-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = "vm-extension-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "vm-extension-nic"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip"
        count                 = 10
      }
    ]
    nsr_rules = []
  }
]

vm_config_list = [{
  role           = "vm-role"
  vm_name        = "vm-extension"
  nic_name       = "vm-extension-nic"
  admin_username = "ubuntu"
  zone           = "1"
  count          = 10
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
}]