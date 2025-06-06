scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-storage"
deletion_delay = "240h"
owner          = "aks"
aks_config_list = [
  {
    role       = "storage"
    aks_name   = "storage-aks"
    dns_prefix = "storage"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_D4ds_v6"
      os_disk_type                 = "Ephemeral"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name         = "user"
        node_count   = 1
        vm_size      = "Standard_NC24ads_A100_v4"
        os_disk_type = "Ephemeral"
        node_labels  = { fio-dedicated = "true" }
        # node_taints  = ["fio-dedicated=true:NoExecute", "fio-dedicated=true:NoSchedule"]
        # zones = ["3"]
      }
    ]
    kubernetes_version = "1.32"
  }
]
