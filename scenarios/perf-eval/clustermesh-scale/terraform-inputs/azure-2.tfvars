scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 2 cluster tier
#
# Mirrors fleet-setup-script.sh with SHARED_VNET=false (separate VNets + peering).
# - 2 VNets (one per cluster) at 10.<id>.0.0/16
# - Per-cluster node subnet (10.<id>.0.0/24) + pod subnet (10.<id>.1.0/24)
# - 2 AKS clusters with Cilium + ACNS, Azure CNI w/ pod subnet (not overlay)
# - Pairwise VNet peering between the two VNets (both directions)
# - Fleet + 2 fleet members (label mesh=true) + clustermeshprofile
#
# Naming:
#   VNet role         : mesh-1, mesh-2                (one VNet per role)
#   AKS role          : mesh-1, mesh-2                (one AKS per role)
#   AKS cluster name  : clustermesh-1, clustermesh-2
#   Fleet member name : mesh-1, mesh-2                (intentionally != cluster name)
#   Fleet name        : clustermesh-flt
#   Profile name      : clustermesh-cmp
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
        address_prefix = "10.1.1.0/24"
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
        address_prefix = "10.2.1.0/24"
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v4"
    }
    extra_node_pool = []
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
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v4"
    }
    extra_node_pool = []
  }
]

# =============================================================================
# Fleet + ClusterMesh (new vars in this scenario)
# =============================================================================
vnet_peering_config = {
  enabled = true
}

fleet_config = {
  enabled      = true
  fleet_name   = "clustermesh-flt"
  cmp_name     = "clustermesh-cmp"
  member_label_key   = "mesh"
  member_label_value = "true"
  members = [
    { member_name = "mesh-1", aks_role = "mesh-1" },
    { member_name = "mesh-2", aks_role = "mesh-2" }
  ]
}
