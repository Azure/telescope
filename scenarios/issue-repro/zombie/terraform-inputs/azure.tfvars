scenario_name  = "k8s-zombie"
scenario_type  = "perf-eval"
deletion_delay = "24h"
aks_config_list = [
  {
    role       = "test"
    aks_name   = "test"
    dns_prefix = "test"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin = "azure"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 3
      vm_size                      = "Standard_DS2_v2"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name       = "testpool1"
        node_count = 1
        vm_size    = "Standard_D8s_v4"
        os_sku     = "Ubuntu"
      },
      {
        name       = "testpool2"
        node_count = 1
        vm_size    = "Standard_D8s_v4"
        os_sku     = "AzureLinux"
      }
    ]
  }
]
