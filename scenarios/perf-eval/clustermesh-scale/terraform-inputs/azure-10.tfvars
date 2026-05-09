scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 10 cluster tier
#
# Same shape as azure-2.tfvars (see that file for full sizing rationale on
# pod CIDR, max-pods, prompool, etc.). This file scales the cluster count
# only; per-cluster sizing is identical to the n2 tier so cluster-count is
# the only variable when comparing tier results.
#
# Generated topology:
#   - 10 VNets (one per cluster) at 10.<id>.0.0/16, id=1..10
#   - 10 AKS clusters (Cilium+ACNS, Azure CNI w/ pod subnet)
#   - 90 VNet peering links (N*(N-1) at separate-VNet mode)
#   - 10 Fleet members (label mesh=true) + 1 clustermeshprofile
#
# Subscription footprint per run (20-node baseline per spec line 24):
#   - default pool: 10 clusters x 20 nodes x D4s_v3 (4 vCPU) = 800 vCPU (DSv3 family)
#   - prompool:     10 clusters x  1 node  x D8s_v3 (8 vCPU) = 80 vCPU (DSv3 family)
#   - total DSv3 compute: 880 vCPU
#   Verify region quota before first run (DSv3 limit is typically 5000 vCPU
#   in eastus2euap; check `az vm list-usage --location eastus2euap`).
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
  },
  {
    role               = "mesh-6"
    vnet_name          = "clustermesh-6-vnet"
    vnet_address_space = "10.6.0.0/16"
    subnet = [
      {
        name           = "clustermesh-6-node"
        address_prefix = "10.6.0.0/24"
      },
      {
        name           = "clustermesh-6-pod"
        address_prefix = "10.6.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-7"
    vnet_name          = "clustermesh-7-vnet"
    vnet_address_space = "10.7.0.0/16"
    subnet = [
      {
        name           = "clustermesh-7-node"
        address_prefix = "10.7.0.0/24"
      },
      {
        name           = "clustermesh-7-pod"
        address_prefix = "10.7.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-8"
    vnet_name          = "clustermesh-8-vnet"
    vnet_address_space = "10.8.0.0/16"
    subnet = [
      {
        name           = "clustermesh-8-node"
        address_prefix = "10.8.0.0/24"
      },
      {
        name           = "clustermesh-8-pod"
        address_prefix = "10.8.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-9"
    vnet_name          = "clustermesh-9-vnet"
    vnet_address_space = "10.9.0.0/16"
    subnet = [
      {
        name           = "clustermesh-9-node"
        address_prefix = "10.9.0.0/24"
      },
      {
        name           = "clustermesh-9-pod"
        address_prefix = "10.9.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-10"
    vnet_name          = "clustermesh-10-vnet"
    vnet_address_space = "10.10.0.0/16"
    subnet = [
      {
        name           = "clustermesh-10-node"
        address_prefix = "10.10.0.0/24"
      },
      {
        name           = "clustermesh-10-pod"
        address_prefix = "10.10.4.0/22"
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
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 20
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v3"
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
    { member_name = "mesh-5", aks_role = "mesh-5" },
    { member_name = "mesh-6", aks_role = "mesh-6" },
    { member_name = "mesh-7", aks_role = "mesh-7" },
    { member_name = "mesh-8", aks_role = "mesh-8" },
    { member_name = "mesh-9", aks_role = "mesh-9" },
    { member_name = "mesh-10", aks_role = "mesh-10" }
  ]
}
