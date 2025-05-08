scenario_type  = "perf-eval"
scenario_name  = "k8s-os-disk"
deletion_delay = "2h"
owner          = "storage"
aks_config_list = [
  {
    role       = "client"
    aks_name   = "disk-aks"
    dns_prefix = "disk"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D16s_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name            = "user"
        node_count      = 1
        vm_size         = "Standard_D16s_v3"
        os_disk_type    = "Managed"
        os_disk_size_gb = 1024
        node_labels     = { fio-dedicated = "true" }
        node_taints     = ["fio-dedicated=true:NoExecute", "fio-dedicated=true:NoSchedule"]
        zones           = ["3"]
      }
    ]
    kubernetes_version = "1.31"
  }
]
