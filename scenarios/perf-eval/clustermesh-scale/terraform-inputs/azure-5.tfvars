scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 5 cluster tier
#
# Same shape as azure-2.tfvars (see that file for full sizing rationale on
# pod CIDR, max-pods, prompool, etc.). This file scales the cluster count
# only; per-cluster sizing is identical to the n2 tier so cluster-count is
# the only variable when comparing tier results.
#
# Generated topology:
#   - 5 VNets (one per cluster) at 10.<id>.0.0/16, id=1..5
#   - 5 AKS clusters (Cilium+ACNS, Azure CNI w/ pod subnet)
#   - 20 VNet peering links (N*(N-1) at separate-VNet mode)
#   - 5 Fleet members (label mesh=true) + 1 clustermeshprofile
#
# Subscription footprint per run:
#   - default pool: 5 clusters x 2 nodes x D4s_v5 (4 vCPU)  = 40 vCPU
#   - prompool:     5 clusters x 1 node  x D8s_v3 (8 vCPU)  = 40 vCPU
#   - total compute: 80 vCPU
#   Verify region quota before first run.
#
# Phase 3 risk surfaces specifically validated at this tier:
#   - Parallel CL2 fan-out at the max_concurrent=4 boundary (5th cluster queues)
#   - VNet peering O(N^2): 20 links provisioned
#   - Fleet member create at scale (5 sequential RP calls)
#   - Network Contributor RBAC propagation across 5 SP-on-VNet assignments
#   - ~/.azure MSAL token-cache race at concurrency 4 (per-cluster CL2 docker)
# =============================================================================

network_config_list = [
  {
    role               = "mesh-1"
    vnet_name          = "clustermesh-1-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "clustermesh-1-node"
        address_prefix = "10.1.0.0/24"
      },
      {
        name           = "clustermesh-1-pod"
        address_prefix = "10.1.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-2"
    vnet_name          = "clustermesh-2-vnet"
    vnet_address_space = "10.2.0.0/16"
    subnet = [
      {
        name           = "clustermesh-2-node"
        address_prefix = "10.2.0.0/24"
      },
      {
        name           = "clustermesh-2-pod"
        address_prefix = "10.2.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-3"
    vnet_name          = "clustermesh-3-vnet"
    vnet_address_space = "10.3.0.0/16"
    subnet = [
      {
        name           = "clustermesh-3-node"
        address_prefix = "10.3.0.0/24"
      },
      {
        name           = "clustermesh-3-pod"
        address_prefix = "10.3.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-4"
    vnet_name          = "clustermesh-4-vnet"
    vnet_address_space = "10.4.0.0/16"
    subnet = [
      {
        name           = "clustermesh-4-node"
        address_prefix = "10.4.0.0/24"
      },
      {
        name           = "clustermesh-4-pod"
        address_prefix = "10.4.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-5"
    vnet_name          = "clustermesh-5-vnet"
    vnet_address_space = "10.5.0.0/16"
    subnet = [
      {
        name           = "clustermesh-5-node"
        address_prefix = "10.5.0.0/24"
      },
      {
        name           = "clustermesh-5-pod"
        address_prefix = "10.5.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  }
]

# =============================================================================
# Fleet + ClusterMesh
# =============================================================================
vnet_peering_config = {
  enabled = true
}

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
    { member_name = "mesh-5", aks_role = "mesh-5" }
  ]
}
