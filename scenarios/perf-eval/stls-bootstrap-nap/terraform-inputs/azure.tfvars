scenario_type  = "perf-eval"
scenario_name  = "stls-bootstrap-nap"
deletion_delay = "2h"
owner          = "aks"

aks_config_list = []

aks_cli_config_list = [
  {
    role               = "nap"
    aks_name           = "nap"
    sku_tier           = "standard"
    managed_cluster_tags = {
      "enable-stls-nap" = "true"
    }
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    kubernetes_version = "1.33"
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D4_v5"
    }
    extra_node_pool = []
    optional_parameters = [
      {
        name  = "node-provisioning-mode"
        value = "Auto"
      },
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      }
    ]
  }
]
