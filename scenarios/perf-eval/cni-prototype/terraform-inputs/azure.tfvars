scenario_type  = "perf-eval"
scenario_name  = "cni-prototype"
deletion_delay = "480h"
owner          = "aks"

network_config_list = [
  {
    role               = "cni"
    vnet_name          = "cni-vnet"
    vnet_address_space = ["10.224.0.0/12", "fd00:5852:d4bf::/48"]
    subnet = [
      {
        name           = "cni-subnet"
        address_prefix = ["10.224.0.0/16", "fd00:5852:d4bf::/64"]
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
      node_count = 2
      vm_size    = "Standard_D16_v5"
    }
    extra_node_pool = [
      {
        name       = "user",
        node_count = 2,
        vm_size    = "Standard_D16ds_v6",
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
        name  = "os-sku"
        value = "Ubuntu2404"
      },
      {
        name = "ip-families"
        value = "IPv4,IPv6"
      }
    ]
  }
]
