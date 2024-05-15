scenario_type  = "perf-eval"
scenario_name  = "vm-same-zone-wrk"
deletion_delay = "72h"
public_ip_config_list = [
  {
    name = "ingress-pip"
  },
  {
    name = "egress-pip"
  }
]
network_config_list = [
  {
    role               = "network"
    vnet_name          = "same-vnet"
    vnet_address_space = "10.2.0.0/16"
    subnet = [{
      name           = "same-subnet"
      address_prefix = "10.2.1.0/24"
    }]
    network_security_group_name = "same-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "server-nic"
        subnet_name           = "same-subnet"
        ip_configuration_name = "server-ipconfig"
        public_ip_name        = "ingress-pip"
      },
      {
        nic_name              = "client-nic"
        subnet_name           = "same-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "egress-pip"
      }
    ]
    nsr_rules = [{
      name                       = "nsr-inbound-ssh"
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
        name                       = "nsr-inbound-http"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "80-80"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-inbound-https"
        priority                   = 102
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Udp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-outbound-http"
        priority                   = 101
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "80-80"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-outbound-https"
        priority                   = 102
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]
loadbalancer_config_list = []
vm_config_list = [
  {
    role           = "client"
    vm_name        = "client-vm"
    nic_name       = "client-nic"
    admin_username = "ubuntu"
    zone           = "3"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-focal"
      sku       = "20_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "server"
    vm_name        = "server-vm"
    nic_name       = "server-nic"
    admin_username = "ubuntu",
    zone           = "3"
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
