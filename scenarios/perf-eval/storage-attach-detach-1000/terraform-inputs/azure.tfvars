scenario_type  = "perf-eval"
scenario_name  = "storage-attach-detach-1000"
deletion_delay = "6h"
owner          = "aks"
aks_config_list = [
  {
    role       = "client"
    aks_name   = "perfevala1000"
    dns_prefix = "attach"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin = "kubenet"
      pod_cidr       = "125.4.0.0/14"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      subnet_name                  = "aks-network"
      vm_size                      = "Standard_D2s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name        = "user"
        node_count  = 40
        subnet_name = "aks-network"
        vm_size     = "Standard_D16s_v3"
        node_labels = { "csi" = "true" }
      }
    ]
    kubernetes_version = "1.33"
  }
]
