scenario_type  = "perf-eval"
scenario_name  = "safeguards-pod-churn-50k"
deletion_delay = "8h"
owner          = "aks"

network_config_list = [
  {
    role               = "slo"
    vnet_name          = "slo-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "slo-subnet-1"
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
    role        = "safeguards"
    aks_name    = "safeguards"
    dns_prefix  = "slo"
    subnet_name = "slo-subnet-1"
    sku_tier    = "Standard"
    azure_policy_enabled = true
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.128.0.0/9"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D16_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    optional_parameters = [
      {
        name  = "safeguards-level"
        value = "Warn"
      }
    ]
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        max_pods             = 110
      },
      {
        name                 = "userpool0"
        node_count           = 300
        auto_scaling_enabled = false
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
      },
      {
        name                 = "userpool1"
        node_count           = 300
        auto_scaling_enabled = false
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
      },
      {
        name                 = "userpool2"
        node_count           = 400
        auto_scaling_enabled = false
        vm_size              = "Standard_D4_v3"
        max_pods             = 110
      }
    ]
    kubernetes_version = "1.31"
  }
]
