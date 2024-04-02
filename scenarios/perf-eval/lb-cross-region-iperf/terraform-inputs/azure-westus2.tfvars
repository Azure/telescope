scenario_type  = "perf-eval"
scenario_name  = "lb-cross-region-iperf"
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
    vnet_address_space = "172.16.0.0/16"
    subnet = [{
      name           = "server-subnet"
      address_prefix = "172.16.0.0/24"
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
        destination_port_range     = "20001-20001"
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
        destination_port_range     = "20002-20002"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
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
    frontend_port            = 20001
    backend_port             = 20001
    fronend_ip_config_prefix = "ingress"
    enable_tcp_reset         = false
    idle_timeout_in_minutes  = 4
    },
    {
      type                    = "Inbound"
      rule_count              = 1
      role                    = "ingress-lb-udp-rule"
      protocol                = "Udp"
      frontend_port           = 20002
      backend_port            = 20002
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