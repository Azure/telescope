scenario_type  = "perf-eval"
scenario_name  = "nsl-nap"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = []

network_config_list = [
  {
    role               = "network"
    vnet_name          = "nsl-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "nsl-subnet"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                  = "client"
    aks_name              = "nsl-nap"
    sku_tier              = "standard"
    subnet_name           = "nsl-subnet"
    managed_identity_name = "nsl-nap-identity"
    kubernetes_version    = "1.36"
    default_node_pool = {
      name       = "system"
      node_count = 3
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
      }
    ]
  }
]
