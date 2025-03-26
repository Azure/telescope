scenario_type  = "perf-eval"
scenario_name  = "cas-c2n5kp5k"
deletion_delay = "5h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "cas"
    aks_name           = "cas-c2n5kp5k"
    sku_tier           = "standard"
    kubernetes_version = "1.31"
    subnet_name        = "cas-subnet"

    default_node_pool = {
      name       = "default"
      node_count = 5
      vm_size    = "Standard_D32ds_v4"
    }
    extra_node_pool = [
      {
        name       = "userpool1"
        node_count = 1
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
            }, {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "min-count"
            value = "1"
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
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
            }, {
            name  = "max-pods"
            value = "110"
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
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
            }, {
            name  = "max-pods"
            value = "110"
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
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
            }, {
            name  = "max-pods"
            value = "110"
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
        name       = "userpool5"
        node_count = 0
        vm_size    = "Standard_D2ds_v4"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
            }, {
            name  = "max-pods"
            value = "110"
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
        name  = "outbound-type"
        value = "managedNATGateway"
      },
      {
        name  = "nat-gateway-managed-outbound-ip-count"
        value = "10"
      },
      {
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      },
      {
        name  = "ca-profile"
        value = "scan-interval=20s scale-down-delay-after-add=2m scale-down-delay-after-failure=1m scale-down-unneeded-time=5m scale-down-unready-time=5m max-graceful-termination-sec=30 skip-nodes-with-local-storage=false max-empty-bulk-delete=1000 max-total-unready-percentage=100 ok-total-unready-count=1000 max-node-provision-time=15m"
      }
] }]
