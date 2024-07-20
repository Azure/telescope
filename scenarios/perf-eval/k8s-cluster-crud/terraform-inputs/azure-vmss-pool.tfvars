scenario_type  = "perf-eval"
scenario_name  = "k8s-cluster-crud"
deletion_delay = "20h"
aks_cli_config_list = [
  {
    role     = "client"
    aks_name = "vmss-pool"
    sku_tier = "standard"

    default_node_pool = {
      name       = "default"
      node_count = 2
      vm_size    = "Standard_D4_v3"
      vm_set_type = "VirtualMachineScaleSets"
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 5
        vm_size    = "Standard_D4_v3"
        vm_set_type = "VirtualMachineScaleSets"
      }
    ]
  }
]
