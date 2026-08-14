scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "4h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 2 cluster tier (SHARED-VNET smoke, canadacentral)
#
# canadacentral port of azure-2-shared.tfvars. Differences from the euap variant
# are SKU family ONLY — everything else (CIDR plan, AKS service-cidr override,
# share-infra mode, probe wiring, Fleet config) is identical so any behavioral
# delta between cc and euap is attributable to (region × SKU family), not test
# shape.
#
# Region selection happens in the pipeline `regions:` array (drives var.location);
# this tfvars file is region-agnostic on its face.
#
# SKU family swap (vs azure-2-shared.tfvars):
#   default_node_pool.vm_size : Standard_D4_v3  -> Standard_D4s_v4
#   prompool.vm_size           : Standard_D8_v3  -> Standard_D8s_v4
#
# Per-cluster vCPU shape is preserved (10×4 + 1×8 = 48 vCPU) so comparison vs
# eastus2euap baseline is apples-to-apples on size.
#
# Why DSv4 in cc (vs Dv3 in euap):
#   - euap sub: 4992 free Dv3, ~0 free DSv4
#   - cc sub (37deca37-...):  62000 free DSv4, low Dv3 headroom
#   The "s" variant (managed disks, no temp disk) is also a strict superset of
#   "non-s" capability for our workload (we don't use temp disk).
#
# Validated by canadacentral-preflight.sh (builds 69226 / 69231 / 69263):
#   D4s_v4: 0 restrictions, 3 zones in cc
#   D8s_v4: 0 restrictions, 3 zones in cc (verified 2026-06-03 ad-hoc)
#   DSv4 family quota: 0/62000 used → 62000 free (need ~96 at n=2, ~4800 at N=100)
#   PIPs:  981 free   (need 2×N = 4 at n=2, 200 at N=100)
#   Fleet: Microsoft.ContainerService is Registered in cc
#
# CIDR plan (identical to euap):
#   VNet shared : 10.0.0.0/8
#   Per cluster id X∈[1..N]:
#     node subnet : 10.<X>.0.0/24
#     pod subnet  : 10.<X>.4.0/22
#   AKS service-cidr  : 192.168.0.0/24 (cluster-local, identical across all)
#   AKS dns-service-ip: 192.168.0.10
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
      { name = "max-pods", value = "110" },
      # Override AKS default service-cidr (10.0.0.0/16) which overlaps with
      # our shared VNet 10.0.0.0/8. See file header for full rationale.
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 10
      auto_scaling_enabled = false
      vm_size              = "Standard_D4s_v4"
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
      vm_size              = "Standard_D4s_v4"
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
    { member_name = "mesh-2", aks_role = "mesh-2" }
  ]
}
