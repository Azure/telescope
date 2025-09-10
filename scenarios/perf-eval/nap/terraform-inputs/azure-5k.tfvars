scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "8h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "nap-nat-gateway-pip"
    count = 5
  }
]

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet"
        address_prefix = "10.192.0.0/10"
      }
    ]
    nat_gateway_associations = [{
      nat_gateway_name = "nap-nat-gateway"
      subnet_names     = ["nap-subnet"]
      public_ip_names  = ["nap-nat-gateway-pip-1", "nap-nat-gateway-pip-2", "nap-nat-gateway-pip-3", "nap-nat-gateway-pip-4", "nap-nat-gateway-pip-5"]
    }]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                  = "nap"
    aks_name              = "nap-5k"
    sku_tier              = "standard"
    subnet_name           = "nap-subnet"
    managed_identity_name = "nap-identity"
    kubernetes_version    = "1.33"
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8_v5"
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
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      },
      {
        name  = "outbound-type"
        value = "userAssignedNATGateway"
      }
    ]
  }
]
