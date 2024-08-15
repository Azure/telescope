scenario_type  = "perf-eval"
scenario_name  = "vm-same-zone-iperf3"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "server-pip"
  },
  {
    name = "client-pip"
  }
]
network_config_list = [
  {
    role               = "server"
    vnet_name          = "server-vnetEG"
    vnet_address_space = "10.2.0.0/16"
    subnet = [{
      name           = "server-subnet"
      address_prefix = "10.2.1.0/24"
    }]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "server-nic"
        subnet_name           = "server-subnet"
        ip_configuration_name = "server-ipconfig"
        public_ip_name        = "server-pip"
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
        destination_port_range     = "20003-20003"
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
        destination_port_range     = "20004-20004"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  },
  {
    role               = "client"
    vnet_name          = "client-vnetEG"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "client-subnet"
      address_prefix = "10.1.1.0/24"
    }]
    network_security_group_name = "client-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "client-pip"
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
        destination_port_range     = "20003-20003"
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
        destination_port_range     = "20004-20004"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]
loadbalancer_config_list = []
vm_config_list = [{
  role           = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  zone           = "1"
  source_image_reference = {
    publisher = "canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  },
  {
    role           = "server"
    vm_name        = "server-vm"
    nic_name       = "server-nic"
    admin_username = "ubuntu",
    zone           = "1"
    source_image_reference = {
      publisher = "canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  }
]
vmss_config_list                  = []
nic_backend_pool_association_list = []
