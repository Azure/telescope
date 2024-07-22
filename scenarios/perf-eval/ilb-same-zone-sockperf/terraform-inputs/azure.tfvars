scenario_type  = "perf-eval"
scenario_name  = "ilb-same-zone-sockperf"
deletion_delay = "2h"
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
        destination_port_range     = "20005-20005"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]
loadbalancer_config_list = [{
  role                  = "ingress"
  loadbalance_name      = "ingress-lb"
  loadbalance_pool_name = "ingress-lb-pool"
  probe_protocol        = "Tcp"
  probe_port            = 20005
  probe_request_path    = null,
  is_internal_lb        = true,
  subnet_name           = "same-subnet",
  lb_rules = [{
    type                     = "Inbound"
    rule_count               = 1
    role                     = "ingress-lb-tcp-rule"
    protocol                 = "Tcp"
    frontend_port            = 20005
    backend_port             = 20005
    fronend_ip_config_prefix = "ingress"
    enable_tcp_reset         = false
    idle_timeout_in_minutes  = 4
  }]
}]
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
    admin_username = "ubuntu"
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
vmss_config_list = []
nic_backend_pool_association_list = [
  {
    nic_name              = "server-nic"
    backend_pool_name     = "ingress-lb-pool"
    vm_name               = "server-vm"
    ip_configuration_name = "server-ipconfig"
  }
]