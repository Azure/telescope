scenario_type  = "perf-eval"
scenario_name  = "k8s-cluster-crud-machine"
deletion_delay = "4h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "crud-nat-gateway-pip"
    count = 5
  }
]
network_config_list = [
  {
    role               = "crud"
    vnet_name          = "crud-vnet"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "crud-subnet"
        address_prefix = "10.192.0.0/10"
      }
    ]
    nat_gateway_associations = [{
      nat_gateway_name = "crud-nat-gateway"
      subnet_names     = ["crud-subnet"]
      public_ip_names  = ["crud-nat-gateway-pip-1", "crud-nat-gateway-pip-2", "crud-nat-gateway-pip-3", "crud-nat-gateway-pip-4", "crud-nat-gateway-pip-5"]
    }]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "mchapi"
    sku_tier                      = "standard"
    subnet_name                   = "crud-subnet"
    managed_identity_name         = "crud-identity"
    use_aks_preview_cli_extension = true
    use_aks_preview_private_build = false
    use_custom_configurations     = false
    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D2_v3"
    }
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
