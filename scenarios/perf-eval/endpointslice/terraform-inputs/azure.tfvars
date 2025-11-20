scenario_type  = "perf-eval"
scenario_name  = "endpointslice"
deletion_delay = "480h"
owner          = "aks"

network_config_list = [
  {
    role               = "endpoint"
    vnet_name          = "endpoint-vnet"
    vnet_address_space = "10.224.0.0/12"
    subnet = [
      {
        name           = "endpoint-subnet"
        address_prefix = "10.224.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                  = "endpoint"
    aks_name              = "endpoint"
    sku_tier              = "standard"
    kubernetes_version    = "1.33"
    subnet_name           = "endpoint-subnet"
    managed_identity_name = "endpoint-identity"
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D8ds_v6"
    }
    extra_node_pool = [
      {
        name       = "user",
        node_count = 10,
        vm_size    = "Standard_D8ds_v6",
        optional_parameters = [
          {
            name  = "node-osdisk-type"
            value = "Ephemeral"
          },
          {
            name  = "os-sku"
            value = "Ubuntu2404"
          }
        ]
      }
    ]
    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "network-dataplane"
        value = "cilium"
      },
      {
        name  = "os-sku"
        value = "Ubuntu2404"
      }
    ]
  }
]
