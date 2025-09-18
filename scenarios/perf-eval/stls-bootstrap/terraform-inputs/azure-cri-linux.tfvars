scenario_type  = "perf-eval"
scenario_name  = "stls-cri-linux"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "client"
    vnet_name          = "stls-cri-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "stls-cri-subnet-1"
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
    role                          = "client"
    aks_name                      = "stls-cri-linux"
    subnet_name                   = "stls-cri-vnet"
    sku_tier                      = "Standard"
    kubernetes_version            = "1.33"
    use_aks_preview_cli_extension = true
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    optional_parameters = [
      { name = "dns-name-prefix", value = "stls-cri" },
      { name = "network-plugin", value = "azure" },
      { name = "network-plugin-mode", value = "overlay" },
      { name = "pod-cidr", value = "10.0.0.0/9" },
      { name = "service-cidr", value = "192.168.0.0/16" },
      { name = "dns-service-ip", value = "192.168.0.10" }
    ]
    default_node_pool = {
      name        = "default"
      node_count  = 3
      vm_size     = "Standard_D16_v5"
      vm_set_type = "VirtualMachineScaleSets"
    }
    extra_node_pool = [
      {
        name        = "prompool"
        node_count  = 1
        vm_size     = "Standard_D16_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "node-labels", value = "prometheus=true" }
        ]
      },
      {
        name        = "userpool0"
        node_count  = 10
        vm_size     = "Standard_D16ds_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "os-disk-type", value = "Ephemeral" },
          { name = "node-taints", value = "cri-resource-consume=true:NoSchedule,cri-resource-consume=true:NoExecute" },
          { name = "node-labels", value = "cri-resource-consume=true" }
        ]
      }
    ]
  }
]
