scenario_name  = "agcperf"
scenario_type  = "perf-eval"
deletion_delay = "6h"

network_config_list = [
  {
    role               = "agcperf"
    vnet_name          = "agcperf-vnet"
    vnet_address_space = "10.10.0.0/16"
    subnet = [{
      name           = "aks-network-agc"
      address_prefix = "10.10.0.0/24"
      delegations = [{
        name                       = "Microsoft.ServiceNetworking.trafficControllers"
        service_delegation_name    = "Microsoft.ServiceNetworking/trafficControllers"
        service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
      }]
      },
      {
        name           = "aks-network-aks"
        address_prefix = "10.10.1.0/24"
    }]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

agc_config_list = [
  {
    role                    = "agcperf"
    name                    = "agc"
    association_subnet_name = "aks-network-agc"
    frontends = [
      "frontend-1",
      "frontend-2",
      "frontend-3",
      "frontend-4",
      "frontend-5",
    ]
  }
]

aks_config_list = [
  {
    role           = "agcperf"
    aks_name       = "aks-instance"
    dns_prefix     = "agcperf"
    subnet_name    = "aks-network-aks"
    network_profile = {
      network_plugin = "azure"
    }
    sku_tier       = "Free"
    default_node_pool = {
      name                         = "systempool"
      node_count                   = 3
      os_disk_type                 = "Managed"
      vm_size                      = "Standard_D4s_v5"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 3
        vm_size    = "Standard_D4s_v5"
      }
    ]
    role_assignment_list = ["Network Contributor"]
  }
]