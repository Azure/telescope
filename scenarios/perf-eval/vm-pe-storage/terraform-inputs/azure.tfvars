scenario_type  = "perf-eval"
scenario_name  = "vm-pe-storage"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "client-pip"
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "same-vnet"
    vnet_address_space = "10.0.0.0/16"
    subnet = [
      {
        name                         = "same-subnet"
        address_prefix               = "10.0.2.0/24"
        pls_network_policies_enabled = false
      }
    ]
    network_security_group_name = "same-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "same-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "client-pip"
      }
    ]
    nsr_rules = [
      {
        name                       = "inbound-nsr-http"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "80-80"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "inbound-nsr-https"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "nsr-ssh"
        priority                   = 102
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "2222"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "outbound-nsr-http"
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
        name                       = "outbound-nsr-https"
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

vm_config_list = [
  {
    role           = "client"
    vm_name        = "client"
    nic_name       = "client-nic"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-focal"
      sku       = "20_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
}]

storage_account_name_prefix = "vmpestorage"

pe_config = {
  pe_name        = "private-endpoint"
  pe_subnet_name = "same-subnet"
  psc_name = "private-service-connection"
  is_manual_connection = false
  subresource_names = ["blob"]
}