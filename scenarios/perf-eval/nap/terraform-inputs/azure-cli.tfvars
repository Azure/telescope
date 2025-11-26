scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "2h"
owner          = "aks"

public_ip_config_list = [
  {
    name = "firewall-pip"
    count = 1
  }
]

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet-ms"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet-ms"
        address_prefix = "10.192.0.0/16"
      },
      {
        name           = "AzureFirewallSubnet"
        address_prefix = "10.193.0.0/26"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
    firewalls = [
      {
        name                  = "nap-firewall"
        sku_tier              = "Standard"
        subnet_name           = "AzureFirewallSubnet"
        public_ip_name        = "firewall-pip"
        threat_intel_mode     = "Alert"
        dns_proxy_enabled     = true
        ip_configuration_name = "nap-fw-ipconfig"
        application_rule_collections = [
          {
            name     = "aksfwar"
            priority = 100
            action   = "Allow"
            rules = [
              {
                name             = "fqdn"
                source_addresses = ["*"]
                target_fqdns     = ["AzureKubernetesService"]
                protocols = [
                  { port = "80", type = "Http" },
                  { port = "443", type = "Https" }
                ]
              }
            ]
          }
        ]
        network_rule_collections = [
          {
            name     = "aksfwnr"
            priority = 100
            action   = "Allow"
            rules = [
              {
                name                  = "apiudp"
                source_addresses      = ["*"]
                destination_addresses = ["AzureCloud"]
                destination_ports     = ["1194"] # vpn/remote access
                protocols             = ["UDP"]
              },
              {
                name                  = "apitcp"
                source_addresses      = ["*"]
                destination_addresses = ["AzureCloud"]
                destination_ports     = ["9000"] # api
                protocols             = ["TCP"]
              },
              {
                name              = "time" 
                source_addresses  = ["*"]
                destination_fqdns = ["ntp.ubuntu.com"]
                destination_ports = ["123"] # network time protocol
                protocols         = ["UDP"]
              }
            ]
          }
        ]
      }
    ]
    route_tables = [
      {
        name                          = "nap-rt"
        bgp_route_propagation_enabled = false
        routes = [
          {
            name                   = "default-route"
            address_prefix         = "0.0.0.0/0"
            next_hop_type          = "VirtualAppliance"
            next_hop_in_ip_address = "firewall:nap-firewall"
          },
          {
            name           = "firewall-internet"
            address_prefix = "publicip:firewall-pip"
            next_hop_type  = "Internet"
          }
        ]
        subnet_associations = [{ subnet_name = "nap-subnet-ms" }]
      }
    ]
  }
]

aks_cli_config_list = [
  {
    role                  = "nap"
    aks_name              = "nap-complex"
    sku_tier              = "standard"
    subnet_name           = "nap-subnet-ms"
    managed_identity_name = "nap-identity"
    kubernetes_version    = "1.33"
    network_profile       = {
        network_plugin = "azure"
        network_plugin_mode = "overlay"
        outbound_type  = "userDefinedRouting"
        pod_cidr       = "10.128.0.0/11" 
    }
    default_node_pool = {
      name       = "system"
      node_count = 1
      vm_size    = "Standard_D4_v2"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "outbound-type"
        value = "userDefinedRouting"
      }
    ]
  }
]