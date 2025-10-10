scenario_type  = "perf-eval"
scenario_name  = "cni-prototype"
deletion_delay = "240h"
owner          = "aks"

network_config_list = [
  {
    role               = "cni"
    vnet_name          = "cni-vnet"
    vnet_address_space = ["172.18.0.0/16", "fd00:ae00::/24"]
    subnet = [
      {
        name           = "cni-subnet"
        address_prefix = ["172.18.0.0/24", "fd00:ae48:be9::/64"]
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role               = "cni"
    aks_name           = "cni-prototype"
    sku_tier           = "standard"
    kubernetes_version = "1.33"
    subnet_name        = "cni-subnet"
    default_node_pool = {
      name       = "default"
      node_count = 3
      vm_size    = "Standard_D8_v5"
    }
    extra_node_pool = [
      {
        name       = "user",
        node_count = 3,
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
        value = "none"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "os-sku"
        value = "Ubuntu2404"
      }
    ]
  }
]
