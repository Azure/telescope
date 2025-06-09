owner          = "akstraffic"
scenario_type  = "perf-eval"
scenario_name  = "lb-k6"
deletion_delay = "4h"

dns_zones = [
  {
    name = "mauricio-1.com"
  },
  {
    name = "mauricio-2.com"
  },
  {
    name = "mauricio-3.com"
  }
]

aks_config_list = [
  {
    role        = "app-routing-test"
    aks_name    = "aks-app-routing"
    dns_prefix  = "aks-app-routing"
    subnet_name = "aks-subnet"
    sku_tier    = "Standard"  
    
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      pod_cidr            = "10.244.0.0/16"
    }
    
    default_node_pool = {
      name                         = "system"
      node_count                   = 1
      vm_size                      = "Standard_D4s_v3"
      only_critical_addons_enabled = true     // Added required field
      temporary_name_for_rotation  = "tempsys" // Added required field
    }
    
    extra_node_pool = [
      {
        name       = "app"
        node_count = 1
        vm_size    = "Standard_D4s_v3"
      }
    ]
    
    web_app_routing = {
      dns_zone_names = ["mauricio-1.com", "mauricio-2.com", "mauricio-3.com"]
    }
  }
]

public_ip_config_list = [
  {
    name  = "pip-app-routing-ingress"
    count = 1
    sku   = "Standard"
  }
]