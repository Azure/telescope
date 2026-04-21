scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "4h"
owner          = "aks"

aks_config_list = []

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet"
        address_prefix = "10.192.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                  = "nap"
    aks_name              = "nap"
    sku_tier              = "standard"
    subnet_name           = "nap-subnet"
    managed_identity_name = "nap-identity"
    kubernetes_version    = "1.33"
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
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
  }
]
