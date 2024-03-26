scenario_type  = "perf-eval"
scenario_name  = "lb-cross-region-jmeter"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "server-pip"
  },
  {
    name = "lb-pip"
  }
]
network_config_list = [
  {
    role               = "network"
    vnet_name          = "server-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [{
      name           = "server-subnet"
      address_prefix = "10.1.1.0/24"
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
        name                       = "nsr-http"
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
        name                       = "nsr-https"
        priority                   = 102
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "server-nsr-https"
        priority                   = 101
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443-443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "server-nsr-ssh"
        priority                   = 102
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "80"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]
cross_region_peering = true
loadbalancer_config_list = [{
  role                  = "ingress"
  loadbalance_name      = "ingress-lb"
  public_ip_name        = "lb-pip"
  loadbalance_pool_name = "ingress-lb-pool"
  probe_protocol        = "Tcp"
  probe_port            = 20000
  probe_request_path    = null,
  lb_rules = [{
    type                     = "Inbound"
    rule_count               = 1
    role                     = "ingress-lb-http-rule"
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
      role                    = "ingress-lb-https-rule"
      protocol                = "Tcp"
      frontend_port           = 443
      backend_port            = 443
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
  }]
}]
vm_config_list = [
  {
    role           = "server"
    vm_name        = "server-vm"
    nic_name       = "server-nic"
    admin_username = "ubuntu"
    zone           = "2"
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