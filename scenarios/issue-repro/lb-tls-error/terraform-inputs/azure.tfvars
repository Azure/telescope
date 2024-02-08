scenario_type  = "issue-repro"
scenario_name  = "lb-tls-error"
deletion_delay = "4h"
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
    role               = "server"
    vnet_name          = "server-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "server-subnet"
      address_prefix = "10.1.1.0/24"
    }]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations  = []
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
      },
      {
        name                       = "server-nsr-http"
        priority                   = 110
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "8080"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "server-nsr-https"
        priority                   = 120
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "4443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  },
  {
    role               = "client"
    vnet_name          = "client-vnet"
    vnet_address_space = "10.0.0.0/16"
    subnet = [{
      name           = "client-subnet"
      address_prefix = "10.0.1.0/24"
    }]
    network_security_group_name = "client-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = null
    }]
    nsr_rules = [{
      name                       = "client-nsr-ssh"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = "*"
      destination_address_prefix = "*"
    }]
  }
]
loadbalancer_config_list = [
  {
    role                  = "ingress"
    loadbalance_name      = "ingress-lb"
    public_ip_name        = "ingress-pip"
    loadbalance_pool_name = "ingress-lb-pool"
    probe_protocol        = "Http"
    probe_port            = 8080
    probe_request_path    = "/healthz"
    lb_rules = [{
      type                    = "Inbound"
      rule_count              = 1
      role                    = "ingress-lb-rule"
      protocol                = "Tcp"
      frontend_port           = 443
      backend_port            = 4443
      enable_tcp_reset        = true
      idle_timeout_in_minutes = 4
      },
      {
        type                    = "Outbound"
        rule_count              = 1
        role                    = "ingress-lb-outbound-rule"
        protocol                = "All"
        frontend_port           = 0
        backend_port            = 0
        enable_tcp_reset        = true
        idle_timeout_in_minutes = 66
    }]
    }, {
    role                  = "egress"
    loadbalance_name      = "egress-lb"
    public_ip_name        = "egress-pip"
    loadbalance_pool_name = "egress-lb-pool"
    probe_protocol        = "Tcp"
    probe_port            = 22
    probe_request_path    = null
    lb_rules = [{
      type                    = "Inbound"
      rule_count              = 1
      role                    = "egress-lb-rule"
      protocol                = "Tcp"
      frontend_port           = 22
      backend_port            = 22
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
      },
      {
        type                    = "Outbound"
        rule_count              = 1
        role                    = "egress-lb-outbound-rule"
        protocol                = "All"
        frontend_port           = 0
        backend_port            = 0
        enable_tcp_reset        = true
        idle_timeout_in_minutes = 4
    }]
  }
]
vm_config_list = [{
  role           = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "adminuser"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  }
]
vmss_config_list = [{
  role                   = "server"
  vmss_name              = "server-vmss"
  nic_name               = "server-nic"
  subnet_name            = "server-subnet"
  loadbalancer_pool_name = "ingress-lb-pool"
  ip_configuration_name  = "server-ipconfig"
  number_of_instances    = 2
  admin_username         = "adminuser"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
}]
nic_backend_pool_association_list = [
  {
    nic_name              = "client-nic"
    backend_pool_name     = "egress-lb-pool"
    vm_name               = "client-vm"
    ip_configuration_name = "client-ipconfig"
  }
]
