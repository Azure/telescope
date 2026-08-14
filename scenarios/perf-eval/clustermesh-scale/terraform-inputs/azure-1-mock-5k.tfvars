scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "24h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — SINGLE-CLUSTER 5k-virtual-node BASELINE
#
# Purpose: the CONSOLIDATED side of the consolidated-vs-sharded comparison. The
# mesh tiers spread virtual nodes across N clusters (100 nodes + 100 mock agents
# per apiserver). This tier puts 5,000 KWOK virtual nodes + 5,000 mock-cilium-
# agents on ONE cluster / ONE apiserver / ONE etcd, with NO mesh fan-out (Fleet
# has a single member, 0 remote peers). Comparing 1x5000 vs N x (5000/N) at the
# SAME total workload isolates single-apiserver scalability from mesh sharding.
#
# WHY 5000 (not 10000): a live threshold ramp (2026-07-07) found a single
# Standard AKS apiserver stays clean under the real pod-churn workload at ~5000
# agents (all measurements gathered, agents stable), but starts SHEDDING the
# agents' watch + node-heartbeat traffic under APF at ~6-8k (agents flap, nodes
# go NotReady) — so the workload can't run cleanly. Operational X ~= 5000 clean.
# (The earlier 10k baseline broke here.)
#
# Same building block as the mesh tiers (KWOK hollow nodes + mock-cilium-agent,
# real Cilium control plane / DryMode datapath), deployed by the
# clustermesh-scale-mock topology (provision-kwok-layer.sh, NODE_COUNT=5000).
#
# FOOTPRINT:
#   - 5k mock-agent Pods are REAL pods on REAL nodes (own Pod IP via Azure CNI).
#     At requests 100m CPU / 256Mi and AKS max-pods=250 they need ~21 nodes by
#     pod count. Default pool = 25 x Standard_D32_v3 (32 vCPU / 128 GiB = 800 vCPU)
#     hosts them with headroom for the per-node system daemonsets.
#   - The 5k virtual nodes are free KWOK API objects (no real compute).
#
# PROMETHEUS (agent metrics scraped): measured live 2026-07-07 — 5,000 mock
# agents = ~5.3M series (~945/agent; mock agents are lean, no datapath) and a
# Prometheus holds it in ~16 GiB, 0 restarts. NOT a cardinality wall. The prompool
# is therefore a modest D32_v3 (128 GiB); the stage sets a 48 GiB Prometheus limit
# (churn headroom). Control-plane-only scrape (if ever needed) fits anywhere.
#
# Naming (single member):
#   VNet role         : mesh-1
#   AKS role          : mesh-1     AKS cluster name : clustermesh-1
#   Fleet member name : mesh-1     Fleet : clustermesh-flt  Profile : clustermesh-cmp
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
        # /18 (16,384 IPs) — Azure CNI assigns a real pod-subnet IP to every one
        # of the ~5k mock-agent Pods + per-node system pods (max-pods 250 x 25
        # nodes = 6,250 pod slots). The churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 podCIDRs), NOT this subnet.
        name           = "clustermesh-1-pod"
        address_prefix = "10.1.64.0/18"
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
      # 250 = Azure-CNI-with-pod-subnet max. 5k mock-agent Pods / 250 = 20 nodes
      # floor; the 25-node pool below leaves ~50 pod slots/node for system pods.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 5,000 mock-cilium-agent Pods (NOT real workload).
    # 25 x D32_v3 = 800 vCPU / 3200 GiB. Agents request 100m/256Mi => 500 vCPU /
    # 1280 GiB of requests, actual ~9m/56Mi each. Sized by pod-count (max-pods) +
    # request headroom for 5000 agents. auto_scaling off for a deterministic footprint.
    default_node_pool = {
      name                 = "default"
      node_count           = 25
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }

    # Dedicated Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here via CL2_PROMETHEUS_NODE_SELECTOR). D32_v3 = 128 GiB — measured live:
    # scraping all 5,000 agents = ~5.3M series / ~16 GiB Prom (mock agents are
    # lean), so 128 GiB is ample (the 10k tier's D64_v3/256 GiB was overkill).
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D32_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  }
]

# =============================================================================
# Fleet + ClusterMesh — DISABLED for the single-cluster baseline.
# A single cluster has no peers, so ClusterMesh is pure overhead: the Fleet
# hub/member-join/CMP + clustermesh-apiserver add ~15-17m of wall-clock and an
# idle apiserver (0 peers, agents publish-only) that would only pollute the
# baseline's control-plane signal. So we drop it. The mock agents get their
# cluster identity from the stage instead of the Fleet-populated cilium-config
# (MOCK_CLUSTER_ID / MOCK_CLUSTER_NAME -> provision-kwok-layer.sh), and the
# mesh-only validate steps are skipped (CLUSTERMESH_FLEET_ENABLED=false).
# =============================================================================
vnet_peering_config = {
  enabled = false
}

fleet_config = {
  enabled            = false
  fleet_name         = "clustermesh-flt"
  cmp_name           = "clustermesh-cmp"
  member_label_key   = "mesh"
  member_label_value = "true"
  members = [
    { member_name = "mesh-1", aks_role = "mesh-1" }
  ]
}
