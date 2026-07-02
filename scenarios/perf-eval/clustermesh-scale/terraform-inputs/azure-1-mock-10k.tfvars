scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "24h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — SINGLE-CLUSTER 10k-virtual-node BASELINE
#
# Purpose: a control experiment for the mesh runs. 72210 spread 10k virtual
# nodes across 100 clusters (100 nodes + 100 mock agents per apiserver, WITH
# ClusterMesh fan-out). This tier puts ALL 10,000 KWOK virtual nodes + 10,000
# mock-cilium-agents on ONE cluster / ONE apiserver / ONE kvstore etcd, with NO
# mesh fan-out (Fleet has a single member, 0 remote peers). Comparing the two
# isolates single-apiserver scalability under 10k cilium agents from the
# cross-cluster mesh dimension.
#
# Same building block as the mesh tiers (KWOK hollow nodes + mock-cilium-agent,
# real Cilium control plane / DryMode datapath), deployed by the
# clustermesh-scale-mock topology (provision-kwok-layer.sh, NODE_COUNT=10000).
# The provision script's >256-node CIDR path + bulk apply make 10k/cluster work.
#
# FOOTPRINT (same total compute as 72210, concentrated in one cluster):
#   - 10k mock-agent Pods are REAL pods on REAL nodes (own Pod IP via Azure CNI).
#     At requests 100m CPU / 256Mi and AKS max-pods=250, they need ~40 nodes by
#     pod count and >=1000 vCPU by request. Default pool = 50 x Standard_D32_v3
#     (32 vCPU / 128 GiB = 1600 vCPU / 6400 GiB) hosts them with headroom for the
#     per-node system daemonsets. Dv3 family (n=100 used Standard_D8_v3) has
#     ~5000 vCPU quota on sub 37deca37; 50 x D32_v3 = 1600 vCPU fits.
#   - The 10k virtual nodes are free KWOK API objects (no real compute).
#
# KNOWN RISK (single-cluster only): one Prometheus now scrapes 10,000 agent
# targets (vs 100/apiserver in the mesh tiers) => ~100x series cardinality. The
# prompool is a big node (D32_v3, 128 GiB) and the stage bumps the Prometheus mem
# limit, but if it still OOMs the mitigation is to sample the agent scrape (only
# the apiserver/etcd control-plane metrics are needed for the baseline, and those
# are low-cardinality). See pipelines/system/new-pipeline-test.yml n1_mock_10k.
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
        # of the ~10k mock-agent Pods + per-node system pods (max-pods 250 x 50
        # nodes = 12,500 pod slots). The churn workload runs on KWOK virtual
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
      # 250 = Azure-CNI-with-pod-subnet max. 10k mock-agent Pods / 250 = 40 nodes
      # floor; the 50-node pool below leaves ~50 pod slots/node for system pods.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 10,000 mock-cilium-agent Pods (NOT real workload).
    # 50 x D32_v3 = 1600 vCPU / 6400 GiB. Agents request 100m/256Mi => 1000 vCPU /
    # 2560 GiB of requests, actual ~9m/56Mi each. Sized by pod-count (max-pods) +
    # request headroom. auto_scaling off for a deterministic baseline footprint.
    default_node_pool = {
      name                 = "default"
      node_count           = 50
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }

    # Dedicated Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here via CL2_PROMETHEUS_NODE_SELECTOR). D32_v3 = 128 GiB for the 10k-target
    # scrape; the stage bumps the Prometheus mem limit to match.
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
# Fleet + ClusterMesh — single member (no peers).
# Kept (rather than dropped) because provision-kwok-layer.sh reads cluster-name/
# cluster-id from the Fleet-populated cilium-config. With one member the mesh has
# 0 remote peers => a clean "no mesh fan-out" baseline; agents run publish-only
# (the stage sets MOCK_CONSUME_CLUSTERMESH=false).
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
    { member_name = "mesh-1", aks_role = "mesh-1" }
  ]
}
