scenario_name  = "k8s-disk"
scenario_type  = "perf-eval"
deletion_delay = "20h"
aks_config_list = [
  {
    role       = "client"
    aks_name   = "disk-aks"
    dns_prefix = "disk"
    network_profile = {
      network_plugin = "azure"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D16s_v4"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "user"
        node_count = 1
        vm_size    = "Standard_D16s_v4"
      }
    ]
  }
]
