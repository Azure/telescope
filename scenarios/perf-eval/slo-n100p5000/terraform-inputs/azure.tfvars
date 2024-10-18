scenario_type  = "perf-eval"
scenario_name  = "slo-n100p5000"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = [
  {
    role        = "slo"
    aks_name    = "slo"
    dns_prefix  = "slo"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 5
      enable_auto_scaling          = false
      vm_size                      = "Standard_D8_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                = "prompool"
        node_count          = 1
        enable_auto_scaling = false
        vm_size             = "Standard_D64_v3"
        max_pods            = 110
        node_labels         = { "prometheus" = "true" }
      },
      {
        name                = "userpool0"
        node_count          = 100
        min_count           = 100
        max_count           = 200
        enable_auto_scaling = true
        vm_size             = "Standard_D4_v3"
        max_pods            = 110
        node_taints         = ["slo=true:NoSchedule"]
        node_labels         = { "slo" = "true" }
      }
      # {
      #   name                = "userpool1"
      #   node_count          = 100
      #   min_count           = 100
      #   max_count           = 500
      #   enable_auto_scaling = true
      #   vm_size             = "Standard_D4_v3"
      #   max_pods            = 110
      #   node_taints         = ["slo=true:NoSchedule"]
      #   node_labels         = { "slo" = "true" }
      # }
    ]
    kubernetes_version = "1.30.4"
  }
]
