scenario_type = "perf-eval"
scenario_name = "clustermesh-scale"
# The full eight-scenario lifecycle can run for 12 hours after provisioning.
# Keep a 24-hour lease so the janitor cannot reap infrastructure mid-suite and
# there is still bounded post-failure inspection time.
deletion_delay = "24h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 2 cluster tier — MOCK variant
# (SHARED-VNET, canadacentral / DSv4)
#
# Canada Central port of azure-2-mock.tfvars. Topology, Fleet membership,
# service CIDRs, mock scale, and lifecycle scenarios are identical; only the
# regional SKU family changes from DSv5 to DSv4.
#
# The original Canada Central blocker was rollout, not capacity: Fleet CRUD
# worked but the ClusterMesh reconciler never projected clustermesh-apiserver.
# That path was verified working on 2026-05-24, followed by a fully green
# shared-VNet n=2 validation in build 69274.
#
# Uses the n=100 shared-VNet topology with the n=2 mock compute footprint: a THIN
# worker pool (2 x Standard_D8s_v4) instead of real workload nodes.
# The 100 virtual nodes/cluster are simulated by KWOK + mock-cilium-agent (real
# Cilium control plane, DryMode datapath), deployed AFTER terraform by the
# clustermesh-scale-mock topology step (provision-kwok-layer.sh). The thin pool
# only hosts the mock-cilium-agent Pods (~9m CPU / ~56Mi each, measured) — 100 of
# them pack onto 2 x D8s_v4 at 5-8% CPU. This is the ~10x vCPU reduction: a real
# node is a whole 4 vCPU VM; a virtual node is a free API object + a tiny Pod.
# See mock-clustermesh/docs/design.md §6.1 for measured footprint.
#
# Mirrors the n=100 topology with one shared VNet and no peerings.
# - 1 shared VNet at 10.0.0.0/8
# - Per-cluster node subnet (10.<id>.0.0/24, 254 IPs) + pod subnet (10.<id>.4.0/22, 1022 IPs)
# - 2 AKS clusters with Cilium + ACNS, Azure CNI w/ pod subnet (not overlay)
# - 0 VNet peerings; pod-to-pod native L3 inside the shared VNet
# - Cluster-local service CIDR 192.168.0.0/24, outside the shared VNet
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
#   VNet role         : shared                        (one VNet for both clusters)
#   AKS role          : mesh-1, mesh-2                (one AKS per role)
#   AKS cluster name  : clustermesh-1, clustermesh-2
#   Fleet member name : mesh-1, mesh-2                (intentionally != cluster name)
#   Fleet name        : clustermesh-flt
#   Profile name      : clustermesh-cmp
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
      # The AKS default 10.0.0.0/16 service CIDR overlaps the shared 10/8 VNet.
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    # Default pool sizing: 20 nodes × D4ds_v4 (4 vCPU / 16GB).
    #
    # 20 nodes per cluster is the spec baseline (scale testing.txt line 24:
    # "20-node clusters as the baseline unit"). Workload sits on this pool;
    # Prometheus is pinned to prompool below to avoid the per-node CPU
    # overcommit + Pending-pods we hit when Prometheus co-tenanted with the
    # workload at smaller node counts.
    #
    # MOCK variant: this default pool is a THIN worker pool (2 x D8s_v4) that only
    # hosts the mock-cilium-agent Pods — NOT 20 real workload nodes. At 100 mock
    # agents/cluster x ~9m CPU / ~56Mi (measured), 100 Pods pack onto 2 x D8s_v4
    # (16 vCPU / 64Gi) at 5-8% CPU. The 100 virtual nodes are KWOK objects with no
    # real compute. SKU D8s_v4 (8 vCPU / 32GB, Cascade Lake): on subscription
    # 37deca37 ("Azure Network Agent - Standalone Test"), the Canada Central
    # DSv4 family has 62,000 vCPU quota. The n=2 mock steady state needs 72
    # vCPU; its mesh-1 churnpool 3→8 scale stimulus peaks at 112 vCPU total.
    # The thin pool hosts only mock-agent Pods + the CL2 measurement client.
    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8s_v4"
    }
    # Dedicated Prometheus node, labeled `prometheus=true`. CL2 is
    # configured (in modules/python/clusterloader2/clustermesh-scale/scale.py
    # via CL2_PROMETHEUS_NODE_SELECTOR) to schedule the prometheus-k8s pod
    # only on this label, so it doesn't compete with workload pods. Mirrors
    # the `prompool` pattern from
    # scenarios/perf-eval/cnl-azurecni-overlay-cilium/terraform-inputs/azure.tfvars.
    # D8s_v4 (8 vCPU / 32GB) is sized for our 1Gi-request Prometheus with
    # ample headroom; matches the family swap of the default pool (62,000
    # Canada Central DSv4 vCPU leave effectively unconstrained n=2 headroom).
    #
    # mesh-1 also has a small, tainted churnpool. Node churn must never target
    # the two-node default pool: those nodes host the bare mock-agent Pods and
    # KWOK controller, so replacing them destroys the test harness instead of
    # measuring isolated node/IP churn. Three real nodes let the n=2 smoke
    # replace two nodes while retaining one Cilium-observed survivor.
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v4"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
      {
        name                 = "churnpool"
        node_count           = 3
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v4"
        optional_parameters = [
          { name = "labels", value = "clustermesh-churn=true" },
          { name = "node-taints", value = "clustermesh-churn=true:NoSchedule" },
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
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8s_v4"
    }
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D8s_v4"
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
  enabled = false
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
