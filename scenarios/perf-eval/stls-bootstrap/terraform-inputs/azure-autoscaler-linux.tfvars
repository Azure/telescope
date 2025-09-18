scenario_type  = "perf-eval"
scenario_name  = "stls-perf-autoscale-linux"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role                          = "cas"
    aks_name                      = "stls-autoscaler"
    subnet_name                   = "aks-network"
    sku_tier                      = "Standard"
    kubernetes_version            = "1.33"
    use_aks_preview_cli_extension = true
    aks_custom_headers = [
      "AKSHTTPCustomFeatures=Microsoft.ContainerService/EnableSecureTLSBootstrapping"
    ]
    optional_parameters = [
      { name = "dns-name-prefix", value = "stls-autoscaler" },
      { name = "network-plugin", value = "azure" },
      { name = "network-plugin-mode", value = "overlay" },
      { name = "pod-cidr", value = "10.128.0.0/11" },
      { name = "enable-cluster-autoscaler", value = "" },
      { name = "cluster-autoscaler-profile", value = "scale-down-delay-after-add=1m,scale-down-delay-after-failure=1m,scale-down-unneeded=1m,scale-down-unready=5m,scan-interval=20s,max-unready-percentage=90,skip-nodes-with-local-storage=false,empty-bulk-delete-max=1000,max-graceful-termination-sec=30" }
    ]
    default_node_pool = {
      name        = "system"
      node_count  = 5
      vm_size     = "Standard_D8ds_v5"
      vm_set_type = "VirtualMachineScaleSets"
    }
    extra_node_pool = [
      {
        name        = "userpool1"
        node_count  = 1
        vm_size     = "Standard_D2ds_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "enable-cluster-autoscaler", value = "" },
          { name = "min-count", value = "1" },
          { name = "max-count", value = "251" },
          { name = "max-pods", value = "110" },
          { name = "node-labels", value = "cas=dedicated" }
        ]
      },
      {
        name        = "userpool2"
        node_count  = 0
        vm_size     = "Standard_D2ds_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "enable-cluster-autoscaler", value = "" },
          { name = "min-count", value = "0" },
          { name = "max-count", value = "250" },
          { name = "max-pods", value = "110" },
          { name = "node-labels", value = "cas=dedicated" }
        ]
      },
      {
        name        = "userpool3"
        node_count  = 0
        vm_size     = "Standard_D2ds_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "enable-cluster-autoscaler", value = "" },
          { name = "min-count", value = "0" },
          { name = "max-count", value = "250" },
          { name = "max-pods", value = "110" },
          { name = "node-labels", value = "cas=dedicated" }
        ]
      },
      {
        name        = "userpool4"
        node_count  = 0
        vm_size     = "Standard_D2ds_v5"
        vm_set_type = "VirtualMachineScaleSets"
        optional_parameters = [
          { name = "enable-cluster-autoscaler", value = "" },
          { name = "min-count", value = "0" },
          { name = "max-count", value = "250" },
          { name = "max-pods", value = "110" },
          { name = "node-labels", value = "cas=dedicated" }
        ]
      }
    ]
  }
]
