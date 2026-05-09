scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 20 cluster tier
#
# Same shape as azure-2.tfvars (see that file for full sizing rationale on
# pod CIDR, max-pods, prompool, etc.). This file scales the cluster count
# only; per-cluster sizing is identical to the n2 tier so cluster-count is
# the only variable when comparing tier results.
#
# Generated topology:
#   - 20 VNets (one per cluster) at 10.<id>.0.0/16, id=1..20
#   - 20 AKS clusters (Cilium+ACNS, Azure CNI w/ pod subnet)
#   - 380 VNet peering links (N*(N-1) at separate-VNet mode)
#   - 20 Fleet members (label mesh=true) + 1 clustermeshprofile
#
# Subscription footprint per run:
#   - default pool: 20 clusters x 2 nodes x D4s_v5 (4 vCPU)  = 160 vCPU
#   - prompool:     20 clusters x 1 node  x D8s_v3 (8 vCPU)  = 160 vCPU
#   - total compute: 320 vCPU
#   Verify region quota before first run.
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
  },
  {
    role               = "mesh-11"
    vnet_name          = "clustermesh-11-vnet"
    vnet_address_space = "10.11.0.0/16"
    subnet = [
      {
        name           = "clustermesh-11-node"
        address_prefix = "10.11.0.0/24"
      },
      {
        name           = "clustermesh-11-pod"
        address_prefix = "10.11.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-12"
    vnet_name          = "clustermesh-12-vnet"
    vnet_address_space = "10.12.0.0/16"
    subnet = [
      {
        name           = "clustermesh-12-node"
        address_prefix = "10.12.0.0/24"
      },
      {
        name           = "clustermesh-12-pod"
        address_prefix = "10.12.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-13"
    vnet_name          = "clustermesh-13-vnet"
    vnet_address_space = "10.13.0.0/16"
    subnet = [
      {
        name           = "clustermesh-13-node"
        address_prefix = "10.13.0.0/24"
      },
      {
        name           = "clustermesh-13-pod"
        address_prefix = "10.13.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-14"
    vnet_name          = "clustermesh-14-vnet"
    vnet_address_space = "10.14.0.0/16"
    subnet = [
      {
        name           = "clustermesh-14-node"
        address_prefix = "10.14.0.0/24"
      },
      {
        name           = "clustermesh-14-pod"
        address_prefix = "10.14.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-15"
    vnet_name          = "clustermesh-15-vnet"
    vnet_address_space = "10.15.0.0/16"
    subnet = [
      {
        name           = "clustermesh-15-node"
        address_prefix = "10.15.0.0/24"
      },
      {
        name           = "clustermesh-15-pod"
        address_prefix = "10.15.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-16"
    vnet_name          = "clustermesh-16-vnet"
    vnet_address_space = "10.16.0.0/16"
    subnet = [
      {
        name           = "clustermesh-16-node"
        address_prefix = "10.16.0.0/24"
      },
      {
        name           = "clustermesh-16-pod"
        address_prefix = "10.16.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-17"
    vnet_name          = "clustermesh-17-vnet"
    vnet_address_space = "10.17.0.0/16"
    subnet = [
      {
        name           = "clustermesh-17-node"
        address_prefix = "10.17.0.0/24"
      },
      {
        name           = "clustermesh-17-pod"
        address_prefix = "10.17.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-18"
    vnet_name          = "clustermesh-18-vnet"
    vnet_address_space = "10.18.0.0/16"
    subnet = [
      {
        name           = "clustermesh-18-node"
        address_prefix = "10.18.0.0/24"
      },
      {
        name           = "clustermesh-18-pod"
        address_prefix = "10.18.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-19"
    vnet_name          = "clustermesh-19-vnet"
    vnet_address_space = "10.19.0.0/16"
    subnet = [
      {
        name           = "clustermesh-19-node"
        address_prefix = "10.19.0.0/24"
      },
      {
        name           = "clustermesh-19-pod"
        address_prefix = "10.19.4.0/22"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  },
  {
    role               = "mesh-20"
    vnet_name          = "clustermesh-20-vnet"
    vnet_address_space = "10.20.0.0/16"
    subnet = [
      {
        name           = "clustermesh-20-node"
        address_prefix = "10.20.0.0/24"
      },
      {
        name           = "clustermesh-20-pod"
        address_prefix = "10.20.4.0/22"
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
