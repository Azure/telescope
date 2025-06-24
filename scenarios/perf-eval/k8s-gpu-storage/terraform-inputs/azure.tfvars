scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-storage"
deletion_delay = "2h"
owner          = "aks"
aks_config_list = [
  {
    role       = "gpu"
    aks_name   = "gpu-storage"
    dns_prefix = "gpu"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      vm_size                      = "Standard_D16ds_v4"
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
        node_taints  = ["fio-dedicated=true:NoExecute", "fio-dedicated=true:NoSchedule"]
      }
    ]
    kubernetes_version = "1.32"
  }
]