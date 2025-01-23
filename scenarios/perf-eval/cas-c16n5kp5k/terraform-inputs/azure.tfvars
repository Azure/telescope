scenario_type  = "perf-eval"
scenario_name  = "cas-c16n5kp5k"
deletion_delay = "5h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "cas"
    aks_name           = "cas-c16n5kp5k"
    sku_tier           = "standard"
    kubernetes_version = "1.31"

    default_node_pool = {
      name       = "default"
      node_count = 5
      vm_size    = "Standard_D16s_v5"
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 0
        vm_size    = "Standard_D2s_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "1000"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool1"
        node_count = 0
        vm_size    = "Standard_D2s_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "1000"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool2"
        node_count = 0
        vm_size    = "Standard_D2s_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "1000"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool3"
        node_count = 0
        vm_size    = "Standard_D2s_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "1000"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool4"
        node_count = 0
        vm_size    = "Standard_D2s_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "1000"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      }
    ]
    optional_parameters = [
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "pod-cidr"
        value = "10.244.0.0/14"
      },
      {
        name  = "outbound-type"
        value = "managedNATGateway"
      },
      {
        name  = "nat-gateway-managed-outbound-ip-count"
        value = "5"
      },
      {
        name  = "nat-gateway-idle-timeout"
        value = "4"
      }
] }]
