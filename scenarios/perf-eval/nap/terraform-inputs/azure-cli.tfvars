scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet-ms"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet-ms"
        address_prefix = "10.192.0.0/10"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
    route_tables = [
        {
            name                          = "nap-rt"
            bgp_route_propagation_enabled = false
            subnet_associations           = [{ subnet_name = "nap-subnet-ms" }]
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
        outbound_type  = "userDefinedRouting"
    }
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8_v5"
    }
    extra_node_pool = []
    optional_parameters = [
    ]
  }
]