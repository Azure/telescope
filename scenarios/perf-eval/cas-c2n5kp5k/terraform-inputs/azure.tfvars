scenario_type  = "perf-eval"
scenario_name  = "cas-c2n5kp5k"
deletion_delay = "5h"
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
    network_security_group_name = "cas-c2n5kp5k-nsg"
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

    default_node_pool = {
      name       = "default"
      node_count = 5
      vm_size    = "Standard_D16s_v5"
    }
    extra_node_pool = [
      {
        name       = "userpool0"
        node_count = 0
        vm_size    = "Standard_D2ds_v5"
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
        name       = "userpool1"
        node_count = 0
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
        vm_size    = "Standard_D2ds_v5"
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
      }
] }]
