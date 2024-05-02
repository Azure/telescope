scenario_type  = "perf-eval"
scenario_name  = "vm-appgateway-vm-jmeter"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "app-gateway-pip"
  },
  {
    name = "client-pip"
  },
  {
    name = "server-pip"
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
    },
    {
      name           = "appgateway-subnet"
      address_prefix = "10.1.2.0/24"
    }]
    network_security_group_name = "server-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "server-nic"
        subnet_name           = "server-subnet"
        ip_configuration_name = "server-ipconfig"
        public_ip_name        = "server-pip"
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
      },
      {
        name                       = "server-nsr-appg"
        priority                   = 103
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "*"
        source_port_range          = "*"
        destination_port_range     = "65200-65535"
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
loadbalancer_config_list = []
appgateway_config_list = [
  {
    role            = "ingress"
    appgateway_name = "appgateway"
    public_ip_name  = "app-gateway-pip"
    subnet_name     = "appgateway-subnet"
    appgateway_probes = [
      {
        name     = "server-http"
        protocol = "Http"
      }
    ]
    appgateway_backend_address_pool = [
      {
        name         = "appgateway-server"
        ip_addresses = ["10.1.1.4"]
      }
    ]
    appgateway_frontend_ports = [
      {
        name = "http"
        port = 80
      }
    ]
    appgateway_backend_http_settings = [
      {
        name                  = "server-http"
        host_name             = "http-backend-direct.mysite.com"
        cookie_based_affinity = "Disabled"
        port                  = 80
        protocol              = "Http"
        request_timeout       = 60
        probe_name            = "server-http"
      }
    ]
    appgateway_http_listeners = [
      {
        name                           = "http-backend-mysite-com-direct"
        frontend_ip_configuration_name = "public"
        frontend_port_name             = "http"
        protocol                       = "Http"
        host_name                      = "http-backend-direct.mysite.com"
      }
    ]
    appgateway_request_routing_rules = [
      {
        name                       = "http-backend-mysite-com-direct"
        priority                   = 1030
        rule_type                  = "Basic"
        http_listener_name         = "http-backend-mysite-com-direct"
        backend_address_pool_name  = "appgateway-server"
        backend_http_settings_name = "server-http"
      }
    ]
  }
]
vm_config_list = [{
  role           = "client"
  vm_name        = "client-vm"
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
  },
  {
    role           = "server"
    vm_name        = "server-vm"
    nic_name       = "server-nic"
    admin_username = "ubuntu"
    zone           = "1"
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
nic_backend_pool_association_list = []
