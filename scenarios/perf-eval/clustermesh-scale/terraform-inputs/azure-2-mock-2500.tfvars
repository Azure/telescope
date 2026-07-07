scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "6h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 2 clusters x 2500 virtual nodes — MOCK variant
#
# The SHARDED side of the consolidated-vs-sharded comparison: 2 clusters x 2500
# KWOK virtual nodes + mock-cilium-agents = 5000 total nodes, same as the 1x5000
# single-cluster baseline, so 1x5000 vs 2x2500 is a fair same-total comparison
# (workload also split: 5000/N pods per cluster). Each cluster's apiserver bears
# only 2500 agents (well below the ~5-7k single-cluster ceiling) + the ClusterMesh
# fan-out. Uses the >250-nodes/cluster mesh podCIDR scheme (MOCK_MESH_STRIDE set in
# the stage) so Pod/node IPs stay unique ACROSS the mesh.
#
# Per cluster: 13 x Standard_D32_v3 default pool (hosts 2500 mock-agent Pods) +
# 1 x Standard_D16_v3 prompool (per-cluster Prometheus). Separate VNets (10.<id>.0.0/16)
# + pairwise peering + Fleet ClusterMesh (mesh-1..mesh-2).
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
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~2500
        # mock-agent Pods a real IP; the churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 CIDRs), NOT this subnet.
        name           = "clustermesh-1-pod"
        address_prefix = "10.1.32.0/19"
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
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~2500
        # mock-agent Pods a real IP; the churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 CIDRs), NOT this subnet.
        name           = "clustermesh-2-pod"
        address_prefix = "10.2.32.0/19"
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
      # Azure CNI w/ pod subnet supports up to 250. 2500 agents / 250 = 10 nodes floor;
      # the 13-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 2500 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 13 x Standard_D32_v3 = 416 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 13
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 2500 agents (~2.4M series / a few GiB), so 64 GiB is ample.
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16_v3"
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
      # Azure CNI w/ pod subnet supports up to 250. 2500 agents / 250 = 10 nodes floor;
      # the 13-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 2500 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 13 x Standard_D32_v3 = 416 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 13
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 2500 agents (~2.4M series / a few GiB), so 64 GiB is ample.
    extra_node_pool = [
      {
        name                 = "prompool"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D16_v3"
        optional_parameters = [
          { name = "labels", value = "prometheus=true" },
        ]
      },
    ]
  }
]

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
