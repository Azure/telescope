scenario_name   = "aks_502_lb_https"
scenario_type = "issue-repro"
deletion_delay  = "4h"
public_ip_names = ["appGateway-pip"]
network_config_list = [
  {
    role                        = "aksNetwork"
    vnet_name                   = "repro502-vnet"
    vnet_address_space          = "10.10.0.0/16"
    subnet_names                = ["aksNetwork-ingress", "aksNetwork-aks"]
    subnet_address_prefixes     = ["10.10.0.0/24", "10.10.1.0/24"]
    network_security_group_name = "aksNetwork-nsg"
    nic_public_ip_associations  = []
    nsr_rules = [
      {
        name                       = "appGateway"
        priority                   = 130
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "65200-65535"
        source_address_prefix      = "GatewayManager"
        destination_address_prefix = "*"
      }
    ]
  }
]
loadbalancer_config_list = []
vm_config_list = []
vmss_config_list = []
nic_backend_pool_association_list = []
appgateway_config_list = [
  {
    role = "aksNetwork"
    appgateway_name = "error_502"
    public_ip_name        = "appGateway-pip"
    subnet_name           = "aksNetwork-aks"
    appgateway_probes = [
      {
        name = "aks-https"
        protocol = "Https"
      },
      {
        name = "aks-http"
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
    appgateway_frontendport = 
    {
      name = "http"
      port = 80
    }
  }
]