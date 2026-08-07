scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 3 cluster tier (SHARED-VNET) — mesh-detach probe baseline
#
# This tfvars variant is the n=3 smoke baseline for the mesh-detach-rejoin
# probe (cluster-loss-recovery scenario). 3 clusters is the minimum for a
# meaningful detach signal: detaching 1 leaves 2 in mesh, observers see
# ready==total==1 (vs N-2=0 at n=2 which is degenerate — can't tell
# "detached" from "never connected").
#
# Topology is the shared-VNet smoke pattern from azure-2-shared.tfvars,
# extended with a 3rd cluster:
#   1. ONE network_config_list entry (role="shared", 10.0.0.0/8) with 4
#      subnets (clustermesh-1-node/pod + clustermesh-2-node/pod). At n=2
#      peered, there are 2 network_config_list entries with 2 subnets each.
#   2. vnet_peering_config.enabled = false (no peerings needed — clusters
#      share the same VNet so pod-to-pod routing is native L3).
#   3. Per-cluster sizing mirrors azure-100.tfvars (node_count=10, Dv3 SKU
#      family) so this smoke validates the exact same per-cluster shape we
#      land at N=100 — if the smoke passes, the ONLY variable at N=100 is
#      cluster count.
#   4. Explicit AKS --service-cidr 192.168.0.0/24 + --dns-service-ip
#      192.168.0.10 because the AKS default service-cidr is 10.0.0.0/16
#      which lives INSIDE our shared VNet's 10.0.0.0/8. Without this
#      override, az aks create rejects with "service-cidr overlaps with
#      virtual-network-cidr". 192.168.0.0/24 is cluster-local — Cilium
#      ClusterMesh global services use the clustermesh-apiserver LB
#      endpoints, not the cluster-local service CIDR, so all clusters can
#      safely use the same service-cidr value.
#
# CIDR plan (matches fleet-setup-script.sh shared-VNet mode reference):
#   VNet shared : 10.0.0.0/8 (16M IPs, fits up to 255 clusters at /24+/22)
#   Per cluster id X∈[1..N]:
#     node subnet : 10.<X>.0.0/24  (254 IPs)
#     pod subnet  : 10.<X>.4.0/22  (1022 IPs, headroom for 200 churn pods)
#   AKS service-cidr : 192.168.0.0/24 (cluster-local; identical across all)
#   AKS dns-service-ip: 192.168.0.10
#
# Why /8 for the VNet (vs /14 from the handoff math):
#   Matches fleet-setup-script.sh:221 — the source-of-truth manual setup
#   uses /8 in shared mode. Preserves the per-cluster /16 cluster-id ↔
#   subnet alignment, identical to peered tfvars naming. Azure VNet limits
#   support /8-/29 — no upper-bound concern at /8.
#
# Naming:
#   VNet role          : shared             (one VNet for both clusters)
#   VNet name          : clustermesh-shared-vnet
#   AKS role           : mesh-1, mesh-2     (same as peered)
#   AKS cluster name   : clustermesh-1, clustermesh-2
#   Fleet member name  : mesh-1, mesh-2
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
      # Override AKS default service-cidr (10.0.0.0/16) which overlaps with
      # our shared VNet 10.0.0.0/8. See file header for full rationale.
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    # Per-cluster sizing mirrors azure-100.tfvars: 10 nodes × D4_v3 + 1 ×
    # D8_v3 = 48 vCPU/cluster. Smoke at n=2 uses 96 vCPU. Sub `37deca37-...`
    # has 4992 free Dv3 (verified 2026-05-19). D{4,8}_v3 (non-`s`) variant
    # picks the standardDv3Family quota bucket which has much more headroom
    # than DSv3 on this sub (see azure-20.tfvars header for full rationale).
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
  }
]

# =============================================================================
# Fleet + ClusterMesh
# =============================================================================
# Peering DISABLED — clusters share the same VNet so pod-to-pod routing is
# native L3. Setting enabled=false also skips the vnet-peering submodule's
# resource creation entirely (azurerm_virtual_network_peering for_each = {}).
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
    { member_name = "mesh-2", aks_role = "mesh-2" },
    { member_name = "mesh-3", aks_role = "mesh-3" }
  ]
}
