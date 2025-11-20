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
        address_prefix = "10.192.0.0/11"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
    route_tables = [
        {
            name                          = "nap-rt"
            bgp_route_propagation_enabled = false
            routes                        = [
                {
                    name                   = "default-route"
                    address_prefix         = "0.0.0.0/0"
                    next_hop_type          = "Internet"
                }
            ]
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
        pod_cidr       = "10.128.0.0/11" 
    }
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D4_v5"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "node-provisioning-mode"
        value = "Auto"
      },
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "outbound-type"
        value = "userDefinedRouting"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      }
    ]
  }
]