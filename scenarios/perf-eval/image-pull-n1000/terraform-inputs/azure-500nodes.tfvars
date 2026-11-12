scenario_type  = "perf-eval"
scenario_name  = "image-pull-n1000"
deletion_delay = "3h"
owner          = "acr"

aks_config_list = [
  {
    role       = "client"
    aks_name   = "img-pull-500"
    dns_prefix = "imgpull"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      outbound_type       = "loadBalancer"
      pod_cidr            = "10.0.0.0/9"
      service_cidr        = "192.168.0.0/16"
      dns_service_ip      = "192.168.0.10"
      load_balancer_profile = {
        managed_outbound_ip_count = 12
        outbound_ports_allocated  = 1024
      }
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D4ds_v5"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D64_v3"
        os_disk_type         = "Managed"
        node_labels          = { "prometheus" = "true" }
      },
      {
        name                 = "userpool"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D4ds_v5"
        os_disk_type         = "Managed"
        node_labels          = { "cri-resource-consume" = "true" }
      }
    ]
  }
]
