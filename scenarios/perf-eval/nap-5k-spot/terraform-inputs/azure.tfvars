scenario_type  = "perf-eval"
scenario_name  = "nap-5k-spot"
deletion_delay = "6h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "nap-nat-gateway-pip"
    count = 5
  }
]
network_config_list = [
  {
    role               = "nap"
    vnet_name          = "nap-vnet"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet"
        address_prefix = "10.192.0.0/10"
      }
    ]
    nat_gateway_associations = [{
      nat_gateway_name = "nap-c2n5kp5k-nat-gateway"
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
    role                          = "nap"
    aks_name                      = "nap-c2n5kp5k"
    sku_tier                      = "standard"
    subnet_name                   = "nap-subnet"
    managed_identity_name         = "nap-identity"
    use_aks_preview_cli_extension = true
    default_node_pool = {
      name        = "default"
      node_count  = 5
      vm_size     = "Standard_D16ds_v5"
      vm_set_type = "VirtualMachineScaleSets"
    }
    aks_custom_headers = ["OverrideControlplaneResources=W3siY29udGFpbmVyTmFtZSI6Imt1YmUtYXBpc2VydmVyIiwiY3B1TGltaXQiOiIzMCIsImNwdVJlcXVlc3QiOiIyNyIsIm1lbW9yeUxpbWl0IjoiNjRHaSIsIm1lbW9yeVJlcXVlc3QiOiI2NEdpIiwiZ29tYXhwcm9jcyI6MzB9XSAg", "ControlPlaneUnderlay=hcp-underlay-eastus2-cx-382", "AKSHTTPCustomFeatures=OverrideControlplaneResources"]
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
        name  = "pod-cidr"
        value = "10.128.0.0/11" // updated to avoid overlap with 10.128.0.0/11
      },
      {
        name  = "outbound-type"
        value = "userAssignedNATGateway"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      }
    ]
  }
]
