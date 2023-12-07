scenario_type   = "perf-eval"
scenario_name   = "storage-blob"
deletion_delay  = "2h"
public_ip_names = ["egress-pip"]
network_config_list = [
  {
    name_prefix                 = "client"
    vnet_name                   = "client-vnet"
    vnet_address_space          = "10.0.0.0/16"
    subnet_names                = ["client-subnet"]
    subnet_address_prefixes     = ["10.0.0.0/24"]
    network_security_group_name = "client-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "egress-pip"
    }]
    nsr_rules = [{
      name                       = "client-nsr-ssh"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "2222"
      source_address_prefix      = "*"
      destination_address_prefix = "*"
    }]
  }
]
loadbalancer_config_list = []

data_disk_config_list = []

vm_config_list = [{
  name_prefix    = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  zone           = 1
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-focal"
    sku       = "20_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  }
]
vmss_config_list                  = []
nic_backend_pool_association_list = []

storage_account_name_prefix = "perfevalblob" # should be same with $STORAGE_ACCOUNT_NAME_PREFIX in the script
