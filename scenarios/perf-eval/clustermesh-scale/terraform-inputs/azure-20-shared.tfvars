scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "48h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 20 cluster tier (SHARED-VNET)
#
# %global variation matrix point — same topology shape as azure-100.tfvars
# (commit df54d53), scaled down to N=20 for the Hemanth/Anubhab
# experiment (vary % namespaces annotated global × cluster count).
#
# Per-cluster sizing (IDENTICAL to azure-100.tfvars):
#   - default pool: 10 × Standard_D4_v3 = 40 vCPU (Dv3)
#   - prompool:     1  × Standard_D8_v3 = 8 vCPU (Dv3)
#   Total per cluster: 48 vCPU. N=20 total: 960 vCPU.
#
# Topology:
#   - 1 shared VNet 10.0.0.0/8
#   - 40 subnets: per cluster id X∈[1..20], node `clustermesh-X-node` at
#     10.<X>.0.0/24 + pod `clustermesh-X-pod` at 10.<X>.4.0/22.
#   - Pod subnets carry the Microsoft.ContainerService/managedClusters delegation.
#   - 0 VNet peerings; pod-to-pod routing native L3 within shared VNet.
#   - AKS service-cidr 192.168.0.0/24 + dns-service-ip 192.168.0.10.
#
# Fleet:
#   - 20 fleet members (mesh-1..mesh-20), labeled mesh=true
#   - 1 clustermeshprofile (clustermesh-cmp) with selector mesh=true
# =============================================================================

network_config_list = [
  {
    role               = "shared"
    vnet_name          = "clustermesh-shared-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "clustermesh-1-node"
        address_prefix = "10.1.0.0/24"
      },
      {
        name           = "clustermesh-1-pod"
        address_prefix = "10.1.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-2-node"
        address_prefix = "10.2.0.0/24"
      },
      {
        name           = "clustermesh-2-pod"
        address_prefix = "10.2.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-3-node"
        address_prefix = "10.3.0.0/24"
      },
      {
        name           = "clustermesh-3-pod"
        address_prefix = "10.3.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-4-node"
        address_prefix = "10.4.0.0/24"
      },
      {
        name           = "clustermesh-4-pod"
        address_prefix = "10.4.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-5-node"
        address_prefix = "10.5.0.0/24"
      },
      {
        name           = "clustermesh-5-pod"
        address_prefix = "10.5.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-6-node"
        address_prefix = "10.6.0.0/24"
      },
      {
        name           = "clustermesh-6-pod"
        address_prefix = "10.6.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-7-node"
        address_prefix = "10.7.0.0/24"
      },
      {
        name           = "clustermesh-7-pod"
        address_prefix = "10.7.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-8-node"
        address_prefix = "10.8.0.0/24"
      },
      {
        name           = "clustermesh-8-pod"
        address_prefix = "10.8.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-9-node"
        address_prefix = "10.9.0.0/24"
      },
      {
        name           = "clustermesh-9-pod"
        address_prefix = "10.9.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-10-node"
        address_prefix = "10.10.0.0/24"
      },
      {
        name           = "clustermesh-10-pod"
        address_prefix = "10.10.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-11-node"
        address_prefix = "10.11.0.0/24"
      },
      {
        name           = "clustermesh-11-pod"
        address_prefix = "10.11.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-12-node"
        address_prefix = "10.12.0.0/24"
      },
      {
        name           = "clustermesh-12-pod"
        address_prefix = "10.12.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-13-node"
        address_prefix = "10.13.0.0/24"
      },
      {
        name           = "clustermesh-13-pod"
        address_prefix = "10.13.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-14-node"
        address_prefix = "10.14.0.0/24"
      },
      {
        name           = "clustermesh-14-pod"
        address_prefix = "10.14.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-15-node"
        address_prefix = "10.15.0.0/24"
      },
      {
        name           = "clustermesh-15-pod"
        address_prefix = "10.15.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-16-node"
        address_prefix = "10.16.0.0/24"
      },
      {
        name           = "clustermesh-16-pod"
        address_prefix = "10.16.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-17-node"
        address_prefix = "10.17.0.0/24"
      },
      {
        name           = "clustermesh-17-pod"
        address_prefix = "10.17.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-18-node"
        address_prefix = "10.18.0.0/24"
      },
      {
        name           = "clustermesh-18-pod"
        address_prefix = "10.18.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-19-node"
        address_prefix = "10.19.0.0/24"
      },
      {
        name           = "clustermesh-19-pod"
        address_prefix = "10.19.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-20-node"
        address_prefix = "10.20.0.0/24"
      },
      {
        name           = "clustermesh-20-pod"
        address_prefix = "10.20.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

# Shared-VNet mode: no peerings needed. Setting enabled=false skips the
# vnet-peering submodule entirely (azurerm_virtual_network_peering for_each = {}).
vnet_peering_config = {
  enabled = false
}

aks_cli_config_list = [
  {
    role                          = "mesh-1"
    aks_name                      = "clustermesh-1"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-1-node"
    pod_subnet_name               = "clustermesh-1-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-2"
    aks_name                      = "clustermesh-2"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-2-node"
    pod_subnet_name               = "clustermesh-2-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-3"
    aks_name                      = "clustermesh-3"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-3-node"
    pod_subnet_name               = "clustermesh-3-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-4"
    aks_name                      = "clustermesh-4"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-4-node"
    pod_subnet_name               = "clustermesh-4-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-5"
    aks_name                      = "clustermesh-5"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-5-node"
    pod_subnet_name               = "clustermesh-5-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-6"
    aks_name                      = "clustermesh-6"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-6-node"
    pod_subnet_name               = "clustermesh-6-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-7"
    aks_name                      = "clustermesh-7"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-7-node"
    pod_subnet_name               = "clustermesh-7-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-8"
    aks_name                      = "clustermesh-8"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-8-node"
    pod_subnet_name               = "clustermesh-8-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-9"
    aks_name                      = "clustermesh-9"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-9-node"
    pod_subnet_name               = "clustermesh-9-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-10"
    aks_name                      = "clustermesh-10"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-10-node"
    pod_subnet_name               = "clustermesh-10-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-11"
    aks_name                      = "clustermesh-11"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-11-node"
    pod_subnet_name               = "clustermesh-11-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-12"
    aks_name                      = "clustermesh-12"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-12-node"
    pod_subnet_name               = "clustermesh-12-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-13"
    aks_name                      = "clustermesh-13"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-13-node"
    pod_subnet_name               = "clustermesh-13-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-14"
    aks_name                      = "clustermesh-14"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-14-node"
    pod_subnet_name               = "clustermesh-14-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-15"
    aks_name                      = "clustermesh-15"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-15-node"
    pod_subnet_name               = "clustermesh-15-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-16"
    aks_name                      = "clustermesh-16"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-16-node"
    pod_subnet_name               = "clustermesh-16-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-17"
    aks_name                      = "clustermesh-17"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-17-node"
    pod_subnet_name               = "clustermesh-17-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-18"
    aks_name                      = "clustermesh-18"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-18-node"
    pod_subnet_name               = "clustermesh-18-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-19"
    aks_name                      = "clustermesh-19"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-19-node"
    pod_subnet_name               = "clustermesh-19-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  },
  {
    role                          = "mesh-20"
    aks_name                      = "clustermesh-20"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-20-node"
    pod_subnet_name               = "clustermesh-20-pod"
    use_aks_preview_cli_extension = true

    optional_parameters = [
      { name = "generate-ssh-keys", value = "" },
      { name = "network-plugin", value = "azure" },
      { name = "network-dataplane", value = "cilium" },
      { name = "enable-acns", value = "" },
      { name = "max-pods", value = "110" },
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4_v3"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  }
]

fleet_config = {
  enabled            = true
  fleet_name         = "clustermesh-flt"
  cmp_name           = "clustermesh-cmp"
  member_label_key   = "mesh"
  member_label_value = "true"
  members = [
    { member_name = "mesh-1", aks_role = "mesh-1" },
    { member_name = "mesh-2", aks_role = "mesh-2" },
    { member_name = "mesh-3", aks_role = "mesh-3" },
    { member_name = "mesh-4", aks_role = "mesh-4" },
    { member_name = "mesh-5", aks_role = "mesh-5" },
    { member_name = "mesh-6", aks_role = "mesh-6" },
    { member_name = "mesh-7", aks_role = "mesh-7" },
    { member_name = "mesh-8", aks_role = "mesh-8" },
    { member_name = "mesh-9", aks_role = "mesh-9" },
    { member_name = "mesh-10", aks_role = "mesh-10" },
    { member_name = "mesh-11", aks_role = "mesh-11" },
    { member_name = "mesh-12", aks_role = "mesh-12" },
    { member_name = "mesh-13", aks_role = "mesh-13" },
    { member_name = "mesh-14", aks_role = "mesh-14" },
    { member_name = "mesh-15", aks_role = "mesh-15" },
    { member_name = "mesh-16", aks_role = "mesh-16" },
    { member_name = "mesh-17", aks_role = "mesh-17" },
    { member_name = "mesh-18", aks_role = "mesh-18" },
    { member_name = "mesh-19", aks_role = "mesh-19" },
    { member_name = "mesh-20", aks_role = "mesh-20" }
  ]
}
