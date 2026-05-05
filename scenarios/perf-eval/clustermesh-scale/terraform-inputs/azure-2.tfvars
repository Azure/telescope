scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 2 cluster tier
#
# Mirrors fleet-setup-script.sh with SHARED_VNET=false (separate VNets + peering).
# - 2 VNets (one per cluster) at 10.<id>.0.0/16
# - Per-cluster node subnet (10.<id>.0.0/24, 254 IPs) + pod subnet (10.<id>.4.0/22, 1022 IPs)
# - 2 AKS clusters with Cilium + ACNS, Azure CNI w/ pod subnet (not overlay)
# - Pairwise VNet peering between the two VNets (both directions)
# - Fleet + 2 fleet members (label mesh=true) + clustermeshprofile
#
# Pod subnet sizing: /22 (1022 IPs) is the floor for any Phase 2 scenario in
# this tier. Math: ~70 baseline pods (kube-system + AKS add-ons across 2 nodes)
# + 200 workload pods (event-throughput n2 tier: 5 ns x 4 dep x 10 replicas)
# = ~270 pods/cluster, plus headroom for future churn-stress / HA scenarios
# without re-touching the network plan. /24 (254 IPs) was insufficient.
# Larger tiers (n5/n10/n20 in Phase 3) will get their own tfvars files with
# subnets sized for their cluster + pod counts.
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
      # AKS default is 30 pods/node. Phase-2 event-throughput workload runs
      # 5ns x 4dep x 10 replicas = 200 pods per cluster; with 2 default-pool
      # nodes that's 100/node, so we need ≥110 to leave headroom for Cilium
      # agent, ACNS daemons, monitoring stack, and kube-system pods. Azure
      # CNI with pod subnet supports up to 250.
      { name = "max-pods", value = "110" },
    ]

    # Default pool sizing: D4s_v5 (4 vCPU / 16GB) is enough for the workload
    # pods alone. Prometheus is pinned to prompool below — without that
    # split, Prometheus's 1Gi+ memory request co-tenanting on default-pool
    # nodes caused per-node CPU overcommit (~160% allocatable) and left
    # workload pods stuck Pending.
    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v5"
    }
    # Dedicated Prometheus node, labeled `prometheus=true`. CL2 is
    # configured (in modules/python/clusterloader2/clustermesh-scale/scale.py
    # via CL2_PROMETHEUS_NODE_SELECTOR) to schedule the prometheus-k8s pod
    # only on this label, so it doesn't compete with workload pods. Mirrors
    # the `prompool` pattern from
    # scenarios/perf-eval/cnl-azurecni-overlay-cilium/terraform-inputs/azure.tfvars.
    # D8s_v3 (8 vCPU / 32GB) is sized for our 1Gi-request Prometheus with
    # ample headroom — much smaller than #1053's D32s_v5 because our
    # workload spec is also much smaller.
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
  }
]

# =============================================================================
# Fleet + ClusterMesh (new vars in this scenario)
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
    { member_name = "mesh-2", aks_role = "mesh-2" }
  ]
}
