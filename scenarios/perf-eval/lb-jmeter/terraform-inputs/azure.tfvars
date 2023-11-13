scenario_name   = "perf_eval_lb_azure"
deletion_delay  = "2h"
public_ip_names = ["ingress-pip", "egress-pip"]
network_config_list = [
  {
    name_prefix                 = "server"
    vnet_name                   = "server-vnet"
    vnet_address_space          = "10.1.0.0/16"
    subnet_names                = ["server-subnet"]
    subnet_address_prefixes     = ["10.1.1.0/24"]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "server-nic"
        subnet_name           = "server-subnet"
        ip_configuration_name = "server-ipconfig"
        public_ip_name        = null
    }]
    nsr_rules = [
      {
        name                       = "server-nsr-http"
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
        name                       = "server-nsr-https"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  },
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
      },
      {
        name                       = "client-nsr-http"
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
        name                       = "client-nsr-https"
        priority                   = 102
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
    }]
  }
]
loadbalancer_config_list = [{
  name_prefix           = "ingress"
  loadbalance_name      = "ingress-lb"
  public_ip_name        = "ingress-pip"
  loadbalance_pool_name = "ingress-lb-pool"
  probe_protocol        = "Tcp"
  probe_port            = 80
  probe_request_path    = null,
  lb_rules = [{
    type                     = "Inbound"
    rule_count               = 1
    name_prefix              = "ingress-lb-http-rule"
    protocol                 = "Tcp"
    frontend_port            = 80
    backend_port             = 80
    fronend_ip_config_prefix = "ingress"
    enable_tcp_reset         = false
    idle_timeout_in_minutes  = 4
    },
    {
      type                    = "Inbound"
      rule_count              = 1
      name_prefix             = "ingress-lb-https-rule"
      protocol                = "Tcp"
      frontend_port           = 443
      backend_port            = 443
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
    },
    {
      type                    = "Outbound"
      rule_count              = 1
      name_prefix             = "ingress-lb-outbound-rule"
      protocol                = "All"
      frontend_port           = 0
      backend_port            = 0
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
  }]
}]

vm_config_list = [{
  name_prefix    = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-focal"
    sku       = "20_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  },
  {
    name_prefix    = "server"
    vm_name        = "server-vm"
    nic_name       = "server-nic"
    admin_username = "ubuntu"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-focal"
      sku       = "20_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  }
]
vmss_config_list = []
nic_backend_pool_association_list = [
  {
    nic_name              = "server-nic"
    backend_pool_name     = "ingress-lb-pool"
    vm_name               = "server-vm"
    ip_configuration_name = "server-ipconfig"
  }
]