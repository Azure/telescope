scenario_type  = "perf-eval"
scenario_name  = "cas-c2n5kp5k"
deletion_delay = "10h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "cas-nat-gateway-pip"
    count = 5
  }
]

network_config_list = [
  {
    role               = "cas"
    vnet_name          = "cas-vnet"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "cas-subnet"
        address_prefix = "10.192.0.0/10"
      }
    ]
    network_security_group_name = ""
    nat_gateway_associations = [{
      nat_gateway_name = "cas-c2n5kp5k-nat-gateway"
      subnet_names     = ["cas-subnet"]
      public_ip_names  = ["cas-nat-gateway-pip-1", "cas-nat-gateway-pip-2", "cas-nat-gateway-pip-3", "cas-nat-gateway-pip-4", "cas-nat-gateway-pip-5"]
      }
    ]
    nic_public_ip_associations = []
    nsr_rules                  = []
  }
]
aks_cli_config_list = [
  {
    role                  = "cas"
    aks_name              = "cas-c2n5kp5k"
    sku_tier              = "standard"
    kubernetes_version    = "1.31"
    subnet_name           = "cas-subnet"
    managed_identity_name = "cas-identity"
    aks_custom_headers    = ["OverrideControlplaneResources=W3siY29udGFpbmVyTmFtZSI6Imt1YmUtYXBpc2VydmVyIiwiY3B1TGltaXQiOiIzMCIsImNwdVJlcXVlc3QiOiIyNyIsIm1lbW9yeUxpbWl0IjoiNjRHaSIsIm1lbW9yeVJlcXVlc3QiOiI2NEdpIiwiZ29tYXhwcm9jcyI6MzB9XSAg", "ControlPlaneUnderlay=hcp-underlay-eastus2-cx-382", "AKSHTTPCustomFeatures=OverrideControlplaneResources"]

    default_node_pool = {
      name       = "default"
      node_count = 5
      vm_size    = "Standard_D16s_v5"
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 1
        vm_size    = "Standard_D2_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "min-count"
            value = "1"
          },
          {
            name  = "max-count"
            value = "500"
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
        vm_size    = "Standard_D2_v5"
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
            value = "500"
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
        vm_size    = "Standard_D2_v5"
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
            value = "500"
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
        vm_size    = "Standard_D2_v5"
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
            value = "500"
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
        vm_size    = "Standard_D2_v5"
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
            value = "500"
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
        vm_size    = "Standard_D2_v5"
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
            value = "500"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool6"
        node_count = 0
        vm_size    = "Standard_D2_v5"
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
            value = "500"
            }, {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool7"
        node_count = 0
        vm_size    = "Standard_D2_v5"
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
            value = "500"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool8"
        node_count = 0
        vm_size    = "Standard_D2_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "min-count"
            value = "0"
            }, {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "max-count"
            value = "500"
          },
          {
            name  = "labels"
            value = "cas=dedicated"
          }
        ]
      },
      {
        name       = "userpool9"
        node_count = 0
        vm_size    = "Standard_D2_v5"
        optional_parameters = [
          {
            name  = "enable-cluster-autoscaler"
            value = ""
          },
          {
            name  = "max-pods"
            value = "110"
          },
          {
            name  = "min-count"
            value = "0"
          },
          {
            name  = "max-count"
            value = "500"
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
        value = "10.128.0.0/11"
      },
      {
        name  = "outbound-type"
        value = "userAssignedNATGateway"
      },
      {
        name  = "ca-profile"
        value = "scan-interval=20s scale-down-delay-after-add=2m scale-down-delay-after-failure=1m scale-down-unneeded-time=3m scale-down-unready-time=5m max-graceful-termination-sec=30 skip-nodes-with-local-storage=false max-empty-bulk-delete=1000 max-total-unready-percentage=90 ok-total-unready-count=950 max-node-provision-time=15m"
      }
] }]
