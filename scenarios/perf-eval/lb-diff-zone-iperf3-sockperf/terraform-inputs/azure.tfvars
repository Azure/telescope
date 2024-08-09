scenario_type  = "perf-eval"
scenario_name  = "lb-diff-zone-iperf3-sockperf"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "client-pip"
  },
  {
    name = "server-pip"
  },
  {
    name = "lb-pip"
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
    nic_public_ip_associations = [
      {
        nic_name              = "server-nic"
        subnet_name           = "server-subnet"
        ip_configuration_name = "server-ipconfig"
        public_ip_name        = "server-pip"
      }
    ]
    nsr_rules = [
      {
        name                       = "server-nsr-tcp"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20003-20005"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "server-nsr-udp"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Udp"
        source_port_range          = "*"
        destination_port_range     = "20004-20004"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "server-nsr-ssh"
        priority                   = 102
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "2222"
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
      address_prefix = "10.0.0.0/24"
    }]
    network_security_group_name = "client-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "client-pip"
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
        name                       = "client-nsr-tcp"
        priority                   = 101
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20003-20005"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "client-nsr-udp"
        priority                   = 102
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Udp"
        source_port_range          = "*"
        destination_port_range     = "20004-20004"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
    }]
  }
]
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
    role                     = "ingress-lb-tcp-rule"
    protocol                 = "Tcp"
    frontend_port            = 20003
    backend_port             = 20003
    fronend_ip_config_prefix = "ingress"
    enable_tcp_reset         = false
    idle_timeout_in_minutes  = 4
    },
    {
      type                    = "Inbound"
      rule_count              = 1
      role                    = "ingress-lb-tcp-rule2"
      protocol                = "Tcp"
      frontend_port           = 20004
      backend_port            = 20004
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
    },
    {
      type                     = "Inbound"
      rule_count               = 1
      role                     = "ingress-lb-tcp-rule3"
      protocol                 = "Tcp"
      frontend_port            = 20005
      backend_port             = 20005
      fronend_ip_config_prefix = "ingress"
      enable_tcp_reset         = false
      idle_timeout_in_minutes  = 4
    },
    {
      type                    = "Inbound"
      rule_count              = 1
      role                    = "ingress-lb-udp-rule"
      protocol                = "Udp"
      frontend_port           = 20004
      backend_port            = 20004
      enable_tcp_reset        = false
      idle_timeout_in_minutes = 4
  }]
}]

vm_config_list = [{
  role           = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  zone           = "1"
  source_image_reference = {
    publisher = "Canonical"
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
    admin_username = "ubuntu"
    zone           = "2"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
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
