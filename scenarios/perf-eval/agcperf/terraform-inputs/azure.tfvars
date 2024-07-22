scenario_name  = "agcperf"
scenario_type  = "perf-eval"
deletion_delay = "6h"

network_config_list = [
  {
    role               = "agcperf"
    vnet_name          = "agcperf-vnet"
    vnet_address_space = "10.224.0.0/12"
    subnet = [{
      name           = "aks-network-agc"
      address_prefix = "10.225.0.0/24"
      delegations = [{
        name                       = "Microsoft.ServiceNetworking.trafficControllers"
        service_delegation_name    = "Microsoft.ServiceNetworking/trafficControllers"
        service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
      }]
      },
      {
        name           = "aks-network-aks"
        address_prefix = "10.224.0.0/16"
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
      "frontend-4"
    ]
  }
]

aks_config_list = [
  {
    role        = "agcperf"
    aks_name    = "aks-instance"
    dns_prefix  = "agcperf"
    sku_tier    = "Standard"
    subnet_name = "aks-network-aks"
    network_profile = {
      network_plugin = "azure"
    }
    default_node_pool = {
      name                         = "systempool"
      node_count                   = 3
      os_disk_type                 = "Managed"
      vm_size                      = "Standard_D8s_v3"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 3
        vm_size    = "Standard_D8s_v3"
        max_pods   = 250
      }
    ]
    role_assignment_list = ["Network Contributor"]
  }
]
