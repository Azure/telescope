scenario_name  = "appgateway-lb-aks-https-502"
scenario_type  = "issue-repro"
deletion_delay = "6h"
public_ip_config_list = [
  {
    name = "app-gateway-pip"
  },
  {
    name = "client-pip"
  }
]
network_config_list = [
  {
    role               = "ingress"
    vnet_name          = "repro502-vnet"
    vnet_address_space = "10.10.0.0/16"
    subnet = [{
      name           = "aks-network-ingress"
      address_prefix = "10.10.0.0/24"
      },
      {
        name           = "aks-network-aks"
        address_prefix = "10.10.1.0/24"
    }]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "client"
    vnet_name          = "client_vnet"
    vnet_address_space = "10.10.0.0/16"
    subnet = [{
      name           = "client-network"
      address_prefix = "10.10.0.0/24"
    }]
    network_security_group_name = "clientnsg"
    nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-network"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "client-pip"
    }]
    nsr_rules = [
      {
        name                       = "client-nsr-ssh"
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
  }
]
loadbalancer_config_list          = []
vmss_config_list                  = []
nic_backend_pool_association_list = []
appgateway_config_list = [
  {
    role            = "ingress"
    appgateway_name = "error_502"
    public_ip_name  = "app-gateway-pip"
    subnet_name     = "aks-network-ingress"
    appgateway_probes = [
      {
        name     = "aks-https"
        protocol = "Https"
      },
      {
        name     = "aks-http"
        protocol = "Http"
      }
    ]
    appgateway_backend_address_pool = [
      {
        name         = "aks-lb"
        ip_addresses = ["10.10.1.250"]
      },
      {
        name         = "aks-direct"
        ip_addresses = ["10.10.1.7", "10.10.1.8", "10.10.1.9"]
      }
    ]
    appgateway_frontendport = {
      name = "http"
      port = 80
    }
    appgateway_backend_http_settings = [
      {
        name                  = "aks-https-lb"
        host_name             = "test.contoso.com"
        cookie_based_affinity = "Disabled"
        port                  = 443
        protocol              = "Https"
        request_timeout       = 60
        probe_name            = "aks-https"
      },
      {
        name                  = "aks-http-lb"
        host_name             = "test.contoso.com"
        cookie_based_affinity = "Disabled"
        port                  = 80
        protocol              = "Http"
        request_timeout       = 60
        probe_name            = "aks-http"
      },
      {
        name                  = "aks-https-direct"
        host_name             = "test.contoso.com"
        cookie_based_affinity = "Disabled"
        port                  = 31291
        protocol              = "Https"
        request_timeout       = 60
        probe_name            = "aks-https"
      },
      {
        name                  = "aks-http-direct"
        host_name             = "test.contoso.com"
        cookie_based_affinity = "Disabled"
        port                  = 31701
        protocol              = "Http"
        request_timeout       = 60
        probe_name            = "aks-http"
      }
    ]
    appgateway_http_listeners = [
      {
        name                           = "https-backend-contoso-com-lb"
        frontend_ip_configuration_name = "public"
        frontend_port_name             = "http"
        protocol                       = "Http"
        host_name                      = "https-backend-lb.contoso.com"
      },
      {
        name                           = "http-backend-contoso-com-lb"
        frontend_ip_configuration_name = "public"
        frontend_port_name             = "http"
        protocol                       = "Http"
        host_name                      = "http-backend-lb.contoso.com"
      },
      {
        name                           = "https-backend-contoso-com-direct"
        frontend_ip_configuration_name = "public"
        frontend_port_name             = "http"
        protocol                       = "Http"
        host_name                      = "https-backend-direct.contoso.com"
      },
      {
        name                           = "http-backend-contoso-com-direct"
        frontend_ip_configuration_name = "public"
        frontend_port_name             = "http"
        protocol                       = "Http"
        host_name                      = "http-backend-direct.contoso.com"
      }
    ]
    appgateway_request_routing_rules = [
      {
        name                       = "https-backend-contoso-com-lb"
        priority                   = 1000
        rule_type                  = "Basic"
        http_listener_name         = "https-backend-contoso-com-lb"
        backend_address_pool_name  = "aks-lb"
        backend_http_settings_name = "aks-https-lb"
      },
      {
        name                       = "http-backend-contoso-com-lb"
        priority                   = 1010
        rule_type                  = "Basic"
        http_listener_name         = "http-backend-contoso-com-lb"
        backend_address_pool_name  = "aks-lb"
        backend_http_settings_name = "aks-http-lb"
      },
      {
        name                       = "https-backend-contoso-com-direct"
        priority                   = 1020
        rule_type                  = "Basic"
        http_listener_name         = "https-backend-contoso-com-direct"
        backend_address_pool_name  = "aks-direct"
        backend_http_settings_name = "aks-https-direct"
      },
      {
        name                       = "http-backend-contoso-com-direct"
        priority                   = 1030
        rule_type                  = "Basic"
        http_listener_name         = "http-backend-contoso-com-direct"
        backend_address_pool_name  = "aks-direct"
        backend_http_settings_name = "aks-http-direct"
      }
    ]
  }
]
aks_config_list = [
  {
    role           = "ingress"
    aks_name       = "aks-instance"
    dns_prefix     = "repro-502"
    subnet_name    = "aks-network-aks"
    network_plugin = "azure"
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "user"
        node_count = 3
      }
    ]
    role_assignment_list = ["Network Contributor"]
  }
]

vm_config_list = [{
  role           = "client"
  vm_name        = "client-vm"
  nic_name       = "client-nic"
  admin_username = "ubuntu"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  }
]
