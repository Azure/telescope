scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "48h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 100 cluster tier — MOCK variant (SHARED-VNET)
#
# Derived from azure-100.tfvars (shared-VNet real n=100): IDENTICAL network,
# fleet, service-cidr, and subnet plan — the ONLY change is the default_node_pool,
# swapped from the real 10 × Standard_D4_v3 workload pool to a THIN 2 × Standard_
# D8_v3 pool that hosts only the mock-cilium-agent Pods. The 100 virtual nodes per
# cluster are simulated by KWOK + mock-cilium-agent (real Cilium control plane,
# DryMode datapath), deployed AFTER terraform by the clustermesh-scale-mock
# topology step (provision-kwok-layer.sh). This is the ~10x vCPU reduction at the
# 10k-node headline tier: a real workload node is a whole VM; a virtual node is a
# free API object + a ~9m-CPU/56Mi Pod. See mock-clustermesh/docs/design.md §6.1.
#
# Validated path: azure-2-mock (build 71645) + azure-20-mock spike (build 71650,
# 19/20 clusters PASS, Fleet meshed all 20). This file is the n=100 shared-VNet
# extrapolation — peered topology is INFEASIBLE here (N*(N-1)=9,900 peerings),
# which is exactly why azure-100.tfvars (and this mock variant) use a shared VNet.
#
# Per-cluster sizing:
#   - default pool: 2 × Standard_D8_v3 = 16 vCPU (Dv3) — hosts 100 mock-agents
#     (~9m CPU/56Mi each, measured) + the CL2 measurement client. max-pods 110.
#   - prompool:     1 × Standard_D8_v3 = 8  vCPU (Dv3) — labeled prometheus=true.
#   Total per cluster: 24 vCPU. N=100 total: 2400 vCPU (vs real n=100's 4800;
#   fits Dv3 family quota on subscription 37deca37, eastus2euap).
#
# Topology (UNCHANGED from azure-100.tfvars):
#   - 1 shared VNet 10.0.0.0/8 (packs 255 clusters cleanly).
#   - 200 subnets: per cluster X∈[1..100], node clustermesh-X-node 10.<X>.0.0/24
#     + pod clustermesh-X-pod 10.<X>.4.0/22 (pod subnet carries the AKS delegation).
#   - 0 VNet peerings (vnet_peering_config.enabled = false); pod-to-pod native L3.
#   - service-cidr 192.168.0.0/24 + dns-service-ip 192.168.0.10 on every cluster.
#
# Fleet:
#   - 100 fleet members (mesh-1..mesh-100), labeled mesh=true
#   - 1 clustermeshprofile (clustermesh-cmp) with selector mesh=true
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
      },
      {
        name           = "clustermesh-4-node"
        address_prefix = "10.4.0.0/24"
      },
      {
        name           = "clustermesh-4-pod"
        address_prefix = "10.4.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-5-node"
        address_prefix = "10.5.0.0/24"
      },
      {
        name           = "clustermesh-5-pod"
        address_prefix = "10.5.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-6-node"
        address_prefix = "10.6.0.0/24"
      },
      {
        name           = "clustermesh-6-pod"
        address_prefix = "10.6.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-7-node"
        address_prefix = "10.7.0.0/24"
      },
      {
        name           = "clustermesh-7-pod"
        address_prefix = "10.7.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-8-node"
        address_prefix = "10.8.0.0/24"
      },
      {
        name           = "clustermesh-8-pod"
        address_prefix = "10.8.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-9-node"
        address_prefix = "10.9.0.0/24"
      },
      {
        name           = "clustermesh-9-pod"
        address_prefix = "10.9.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-10-node"
        address_prefix = "10.10.0.0/24"
      },
      {
        name           = "clustermesh-10-pod"
        address_prefix = "10.10.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-11-node"
        address_prefix = "10.11.0.0/24"
      },
      {
        name           = "clustermesh-11-pod"
        address_prefix = "10.11.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-12-node"
        address_prefix = "10.12.0.0/24"
      },
      {
        name           = "clustermesh-12-pod"
        address_prefix = "10.12.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-13-node"
        address_prefix = "10.13.0.0/24"
      },
      {
        name           = "clustermesh-13-pod"
        address_prefix = "10.13.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-14-node"
        address_prefix = "10.14.0.0/24"
      },
      {
        name           = "clustermesh-14-pod"
        address_prefix = "10.14.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-15-node"
        address_prefix = "10.15.0.0/24"
      },
      {
        name           = "clustermesh-15-pod"
        address_prefix = "10.15.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-16-node"
        address_prefix = "10.16.0.0/24"
      },
      {
        name           = "clustermesh-16-pod"
        address_prefix = "10.16.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-17-node"
        address_prefix = "10.17.0.0/24"
      },
      {
        name           = "clustermesh-17-pod"
        address_prefix = "10.17.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-18-node"
        address_prefix = "10.18.0.0/24"
      },
      {
        name           = "clustermesh-18-pod"
        address_prefix = "10.18.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-19-node"
        address_prefix = "10.19.0.0/24"
      },
      {
        name           = "clustermesh-19-pod"
        address_prefix = "10.19.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-20-node"
        address_prefix = "10.20.0.0/24"
      },
      {
        name           = "clustermesh-20-pod"
        address_prefix = "10.20.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-21-node"
        address_prefix = "10.21.0.0/24"
      },
      {
        name           = "clustermesh-21-pod"
        address_prefix = "10.21.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-22-node"
        address_prefix = "10.22.0.0/24"
      },
      {
        name           = "clustermesh-22-pod"
        address_prefix = "10.22.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-23-node"
        address_prefix = "10.23.0.0/24"
      },
      {
        name           = "clustermesh-23-pod"
        address_prefix = "10.23.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-24-node"
        address_prefix = "10.24.0.0/24"
      },
      {
        name           = "clustermesh-24-pod"
        address_prefix = "10.24.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-25-node"
        address_prefix = "10.25.0.0/24"
      },
      {
        name           = "clustermesh-25-pod"
        address_prefix = "10.25.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-26-node"
        address_prefix = "10.26.0.0/24"
      },
      {
        name           = "clustermesh-26-pod"
        address_prefix = "10.26.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-27-node"
        address_prefix = "10.27.0.0/24"
      },
      {
        name           = "clustermesh-27-pod"
        address_prefix = "10.27.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-28-node"
        address_prefix = "10.28.0.0/24"
      },
      {
        name           = "clustermesh-28-pod"
        address_prefix = "10.28.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-29-node"
        address_prefix = "10.29.0.0/24"
      },
      {
        name           = "clustermesh-29-pod"
        address_prefix = "10.29.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-30-node"
        address_prefix = "10.30.0.0/24"
      },
      {
        name           = "clustermesh-30-pod"
        address_prefix = "10.30.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-31-node"
        address_prefix = "10.31.0.0/24"
      },
      {
        name           = "clustermesh-31-pod"
        address_prefix = "10.31.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-32-node"
        address_prefix = "10.32.0.0/24"
      },
      {
        name           = "clustermesh-32-pod"
        address_prefix = "10.32.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-33-node"
        address_prefix = "10.33.0.0/24"
      },
      {
        name           = "clustermesh-33-pod"
        address_prefix = "10.33.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-34-node"
        address_prefix = "10.34.0.0/24"
      },
      {
        name           = "clustermesh-34-pod"
        address_prefix = "10.34.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-35-node"
        address_prefix = "10.35.0.0/24"
      },
      {
        name           = "clustermesh-35-pod"
        address_prefix = "10.35.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-36-node"
        address_prefix = "10.36.0.0/24"
      },
      {
        name           = "clustermesh-36-pod"
        address_prefix = "10.36.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-37-node"
        address_prefix = "10.37.0.0/24"
      },
      {
        name           = "clustermesh-37-pod"
        address_prefix = "10.37.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-38-node"
        address_prefix = "10.38.0.0/24"
      },
      {
        name           = "clustermesh-38-pod"
        address_prefix = "10.38.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-39-node"
        address_prefix = "10.39.0.0/24"
      },
      {
        name           = "clustermesh-39-pod"
        address_prefix = "10.39.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-40-node"
        address_prefix = "10.40.0.0/24"
      },
      {
        name           = "clustermesh-40-pod"
        address_prefix = "10.40.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-41-node"
        address_prefix = "10.41.0.0/24"
      },
      {
        name           = "clustermesh-41-pod"
        address_prefix = "10.41.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-42-node"
        address_prefix = "10.42.0.0/24"
      },
      {
        name           = "clustermesh-42-pod"
        address_prefix = "10.42.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-43-node"
        address_prefix = "10.43.0.0/24"
      },
      {
        name           = "clustermesh-43-pod"
        address_prefix = "10.43.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-44-node"
        address_prefix = "10.44.0.0/24"
      },
      {
        name           = "clustermesh-44-pod"
        address_prefix = "10.44.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-45-node"
        address_prefix = "10.45.0.0/24"
      },
      {
        name           = "clustermesh-45-pod"
        address_prefix = "10.45.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-46-node"
        address_prefix = "10.46.0.0/24"
      },
      {
        name           = "clustermesh-46-pod"
        address_prefix = "10.46.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-47-node"
        address_prefix = "10.47.0.0/24"
      },
      {
        name           = "clustermesh-47-pod"
        address_prefix = "10.47.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-48-node"
        address_prefix = "10.48.0.0/24"
      },
      {
        name           = "clustermesh-48-pod"
        address_prefix = "10.48.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-49-node"
        address_prefix = "10.49.0.0/24"
      },
      {
        name           = "clustermesh-49-pod"
        address_prefix = "10.49.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-50-node"
        address_prefix = "10.50.0.0/24"
      },
      {
        name           = "clustermesh-50-pod"
        address_prefix = "10.50.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-51-node"
        address_prefix = "10.51.0.0/24"
      },
      {
        name           = "clustermesh-51-pod"
        address_prefix = "10.51.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-52-node"
        address_prefix = "10.52.0.0/24"
      },
      {
        name           = "clustermesh-52-pod"
        address_prefix = "10.52.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-53-node"
        address_prefix = "10.53.0.0/24"
      },
      {
        name           = "clustermesh-53-pod"
        address_prefix = "10.53.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-54-node"
        address_prefix = "10.54.0.0/24"
      },
      {
        name           = "clustermesh-54-pod"
        address_prefix = "10.54.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-55-node"
        address_prefix = "10.55.0.0/24"
      },
      {
        name           = "clustermesh-55-pod"
        address_prefix = "10.55.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-56-node"
        address_prefix = "10.56.0.0/24"
      },
      {
        name           = "clustermesh-56-pod"
        address_prefix = "10.56.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-57-node"
        address_prefix = "10.57.0.0/24"
      },
      {
        name           = "clustermesh-57-pod"
        address_prefix = "10.57.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-58-node"
        address_prefix = "10.58.0.0/24"
      },
      {
        name           = "clustermesh-58-pod"
        address_prefix = "10.58.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-59-node"
        address_prefix = "10.59.0.0/24"
      },
      {
        name           = "clustermesh-59-pod"
        address_prefix = "10.59.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-60-node"
        address_prefix = "10.60.0.0/24"
      },
      {
        name           = "clustermesh-60-pod"
        address_prefix = "10.60.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-61-node"
        address_prefix = "10.61.0.0/24"
      },
      {
        name           = "clustermesh-61-pod"
        address_prefix = "10.61.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-62-node"
        address_prefix = "10.62.0.0/24"
      },
      {
        name           = "clustermesh-62-pod"
        address_prefix = "10.62.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-63-node"
        address_prefix = "10.63.0.0/24"
      },
      {
        name           = "clustermesh-63-pod"
        address_prefix = "10.63.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-64-node"
        address_prefix = "10.64.0.0/24"
      },
      {
        name           = "clustermesh-64-pod"
        address_prefix = "10.64.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-65-node"
        address_prefix = "10.65.0.0/24"
      },
      {
        name           = "clustermesh-65-pod"
        address_prefix = "10.65.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-66-node"
        address_prefix = "10.66.0.0/24"
      },
      {
        name           = "clustermesh-66-pod"
        address_prefix = "10.66.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-67-node"
        address_prefix = "10.67.0.0/24"
      },
      {
        name           = "clustermesh-67-pod"
        address_prefix = "10.67.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-68-node"
        address_prefix = "10.68.0.0/24"
      },
      {
        name           = "clustermesh-68-pod"
        address_prefix = "10.68.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-69-node"
        address_prefix = "10.69.0.0/24"
      },
      {
        name           = "clustermesh-69-pod"
        address_prefix = "10.69.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-70-node"
        address_prefix = "10.70.0.0/24"
      },
      {
        name           = "clustermesh-70-pod"
        address_prefix = "10.70.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-71-node"
        address_prefix = "10.71.0.0/24"
      },
      {
        name           = "clustermesh-71-pod"
        address_prefix = "10.71.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-72-node"
        address_prefix = "10.72.0.0/24"
      },
      {
        name           = "clustermesh-72-pod"
        address_prefix = "10.72.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-73-node"
        address_prefix = "10.73.0.0/24"
      },
      {
        name           = "clustermesh-73-pod"
        address_prefix = "10.73.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-74-node"
        address_prefix = "10.74.0.0/24"
      },
      {
        name           = "clustermesh-74-pod"
        address_prefix = "10.74.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-75-node"
        address_prefix = "10.75.0.0/24"
      },
      {
        name           = "clustermesh-75-pod"
        address_prefix = "10.75.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-76-node"
        address_prefix = "10.76.0.0/24"
      },
      {
        name           = "clustermesh-76-pod"
        address_prefix = "10.76.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-77-node"
        address_prefix = "10.77.0.0/24"
      },
      {
        name           = "clustermesh-77-pod"
        address_prefix = "10.77.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-78-node"
        address_prefix = "10.78.0.0/24"
      },
      {
        name           = "clustermesh-78-pod"
        address_prefix = "10.78.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-79-node"
        address_prefix = "10.79.0.0/24"
      },
      {
        name           = "clustermesh-79-pod"
        address_prefix = "10.79.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-80-node"
        address_prefix = "10.80.0.0/24"
      },
      {
        name           = "clustermesh-80-pod"
        address_prefix = "10.80.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-81-node"
        address_prefix = "10.81.0.0/24"
      },
      {
        name           = "clustermesh-81-pod"
        address_prefix = "10.81.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-82-node"
        address_prefix = "10.82.0.0/24"
      },
      {
        name           = "clustermesh-82-pod"
        address_prefix = "10.82.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-83-node"
        address_prefix = "10.83.0.0/24"
      },
      {
        name           = "clustermesh-83-pod"
        address_prefix = "10.83.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-84-node"
        address_prefix = "10.84.0.0/24"
      },
      {
        name           = "clustermesh-84-pod"
        address_prefix = "10.84.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-85-node"
        address_prefix = "10.85.0.0/24"
      },
      {
        name           = "clustermesh-85-pod"
        address_prefix = "10.85.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-86-node"
        address_prefix = "10.86.0.0/24"
      },
      {
        name           = "clustermesh-86-pod"
        address_prefix = "10.86.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-87-node"
        address_prefix = "10.87.0.0/24"
      },
      {
        name           = "clustermesh-87-pod"
        address_prefix = "10.87.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-88-node"
        address_prefix = "10.88.0.0/24"
      },
      {
        name           = "clustermesh-88-pod"
        address_prefix = "10.88.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-89-node"
        address_prefix = "10.89.0.0/24"
      },
      {
        name           = "clustermesh-89-pod"
        address_prefix = "10.89.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-90-node"
        address_prefix = "10.90.0.0/24"
      },
      {
        name           = "clustermesh-90-pod"
        address_prefix = "10.90.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-91-node"
        address_prefix = "10.91.0.0/24"
      },
      {
        name           = "clustermesh-91-pod"
        address_prefix = "10.91.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-92-node"
        address_prefix = "10.92.0.0/24"
      },
      {
        name           = "clustermesh-92-pod"
        address_prefix = "10.92.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-93-node"
        address_prefix = "10.93.0.0/24"
      },
      {
        name           = "clustermesh-93-pod"
        address_prefix = "10.93.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-94-node"
        address_prefix = "10.94.0.0/24"
      },
      {
        name           = "clustermesh-94-pod"
        address_prefix = "10.94.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-95-node"
        address_prefix = "10.95.0.0/24"
      },
      {
        name           = "clustermesh-95-pod"
        address_prefix = "10.95.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-96-node"
        address_prefix = "10.96.0.0/24"
      },
      {
        name           = "clustermesh-96-pod"
        address_prefix = "10.96.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-97-node"
        address_prefix = "10.97.0.0/24"
      },
      {
        name           = "clustermesh-97-pod"
        address_prefix = "10.97.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-98-node"
        address_prefix = "10.98.0.0/24"
      },
      {
        name           = "clustermesh-98-pod"
        address_prefix = "10.98.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-99-node"
        address_prefix = "10.99.0.0/24"
      },
      {
        name           = "clustermesh-99-pod"
        address_prefix = "10.99.4.0/22"
        delegations = [
          {
            name                       = "aks-delegation"
            service_delegation_name    = "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
          }
        ]
      },
      {
        name           = "clustermesh-100-node"
        address_prefix = "10.100.0.0/24"
      },
      {
        name           = "clustermesh-100-pod"
        address_prefix = "10.100.4.0/22"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
      { name = "service-cidr", value = "192.168.0.0/24" },
      { name = "dns-service-ip", value = "192.168.0.10" },
    ]

    default_node_pool = {
      name                 = "default"
      node_count           = 2
      auto_scaling_enabled = false
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-21"
    aks_name                      = "clustermesh-21"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-21-node"
    pod_subnet_name               = "clustermesh-21-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-22"
    aks_name                      = "clustermesh-22"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-22-node"
    pod_subnet_name               = "clustermesh-22-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-23"
    aks_name                      = "clustermesh-23"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-23-node"
    pod_subnet_name               = "clustermesh-23-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-24"
    aks_name                      = "clustermesh-24"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-24-node"
    pod_subnet_name               = "clustermesh-24-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-25"
    aks_name                      = "clustermesh-25"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-25-node"
    pod_subnet_name               = "clustermesh-25-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-26"
    aks_name                      = "clustermesh-26"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-26-node"
    pod_subnet_name               = "clustermesh-26-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-27"
    aks_name                      = "clustermesh-27"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-27-node"
    pod_subnet_name               = "clustermesh-27-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-28"
    aks_name                      = "clustermesh-28"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-28-node"
    pod_subnet_name               = "clustermesh-28-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-29"
    aks_name                      = "clustermesh-29"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-29-node"
    pod_subnet_name               = "clustermesh-29-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-30"
    aks_name                      = "clustermesh-30"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-30-node"
    pod_subnet_name               = "clustermesh-30-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-31"
    aks_name                      = "clustermesh-31"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-31-node"
    pod_subnet_name               = "clustermesh-31-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-32"
    aks_name                      = "clustermesh-32"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-32-node"
    pod_subnet_name               = "clustermesh-32-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-33"
    aks_name                      = "clustermesh-33"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-33-node"
    pod_subnet_name               = "clustermesh-33-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-34"
    aks_name                      = "clustermesh-34"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-34-node"
    pod_subnet_name               = "clustermesh-34-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-35"
    aks_name                      = "clustermesh-35"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-35-node"
    pod_subnet_name               = "clustermesh-35-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-36"
    aks_name                      = "clustermesh-36"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-36-node"
    pod_subnet_name               = "clustermesh-36-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-37"
    aks_name                      = "clustermesh-37"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-37-node"
    pod_subnet_name               = "clustermesh-37-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-38"
    aks_name                      = "clustermesh-38"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-38-node"
    pod_subnet_name               = "clustermesh-38-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-39"
    aks_name                      = "clustermesh-39"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-39-node"
    pod_subnet_name               = "clustermesh-39-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-40"
    aks_name                      = "clustermesh-40"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-40-node"
    pod_subnet_name               = "clustermesh-40-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-41"
    aks_name                      = "clustermesh-41"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-41-node"
    pod_subnet_name               = "clustermesh-41-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-42"
    aks_name                      = "clustermesh-42"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-42-node"
    pod_subnet_name               = "clustermesh-42-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-43"
    aks_name                      = "clustermesh-43"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-43-node"
    pod_subnet_name               = "clustermesh-43-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-44"
    aks_name                      = "clustermesh-44"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-44-node"
    pod_subnet_name               = "clustermesh-44-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-45"
    aks_name                      = "clustermesh-45"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-45-node"
    pod_subnet_name               = "clustermesh-45-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-46"
    aks_name                      = "clustermesh-46"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-46-node"
    pod_subnet_name               = "clustermesh-46-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-47"
    aks_name                      = "clustermesh-47"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-47-node"
    pod_subnet_name               = "clustermesh-47-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-48"
    aks_name                      = "clustermesh-48"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-48-node"
    pod_subnet_name               = "clustermesh-48-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-49"
    aks_name                      = "clustermesh-49"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-49-node"
    pod_subnet_name               = "clustermesh-49-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-50"
    aks_name                      = "clustermesh-50"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-50-node"
    pod_subnet_name               = "clustermesh-50-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-51"
    aks_name                      = "clustermesh-51"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-51-node"
    pod_subnet_name               = "clustermesh-51-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-52"
    aks_name                      = "clustermesh-52"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-52-node"
    pod_subnet_name               = "clustermesh-52-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-53"
    aks_name                      = "clustermesh-53"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-53-node"
    pod_subnet_name               = "clustermesh-53-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-54"
    aks_name                      = "clustermesh-54"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-54-node"
    pod_subnet_name               = "clustermesh-54-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-55"
    aks_name                      = "clustermesh-55"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-55-node"
    pod_subnet_name               = "clustermesh-55-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-56"
    aks_name                      = "clustermesh-56"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-56-node"
    pod_subnet_name               = "clustermesh-56-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-57"
    aks_name                      = "clustermesh-57"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-57-node"
    pod_subnet_name               = "clustermesh-57-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-58"
    aks_name                      = "clustermesh-58"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-58-node"
    pod_subnet_name               = "clustermesh-58-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-59"
    aks_name                      = "clustermesh-59"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-59-node"
    pod_subnet_name               = "clustermesh-59-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-60"
    aks_name                      = "clustermesh-60"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-60-node"
    pod_subnet_name               = "clustermesh-60-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-61"
    aks_name                      = "clustermesh-61"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-61-node"
    pod_subnet_name               = "clustermesh-61-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-62"
    aks_name                      = "clustermesh-62"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-62-node"
    pod_subnet_name               = "clustermesh-62-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-63"
    aks_name                      = "clustermesh-63"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-63-node"
    pod_subnet_name               = "clustermesh-63-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-64"
    aks_name                      = "clustermesh-64"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-64-node"
    pod_subnet_name               = "clustermesh-64-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-65"
    aks_name                      = "clustermesh-65"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-65-node"
    pod_subnet_name               = "clustermesh-65-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-66"
    aks_name                      = "clustermesh-66"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-66-node"
    pod_subnet_name               = "clustermesh-66-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-67"
    aks_name                      = "clustermesh-67"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-67-node"
    pod_subnet_name               = "clustermesh-67-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-68"
    aks_name                      = "clustermesh-68"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-68-node"
    pod_subnet_name               = "clustermesh-68-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-69"
    aks_name                      = "clustermesh-69"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-69-node"
    pod_subnet_name               = "clustermesh-69-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-70"
    aks_name                      = "clustermesh-70"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-70-node"
    pod_subnet_name               = "clustermesh-70-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-71"
    aks_name                      = "clustermesh-71"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-71-node"
    pod_subnet_name               = "clustermesh-71-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-72"
    aks_name                      = "clustermesh-72"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-72-node"
    pod_subnet_name               = "clustermesh-72-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-73"
    aks_name                      = "clustermesh-73"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-73-node"
    pod_subnet_name               = "clustermesh-73-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-74"
    aks_name                      = "clustermesh-74"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-74-node"
    pod_subnet_name               = "clustermesh-74-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-75"
    aks_name                      = "clustermesh-75"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-75-node"
    pod_subnet_name               = "clustermesh-75-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-76"
    aks_name                      = "clustermesh-76"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-76-node"
    pod_subnet_name               = "clustermesh-76-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-77"
    aks_name                      = "clustermesh-77"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-77-node"
    pod_subnet_name               = "clustermesh-77-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-78"
    aks_name                      = "clustermesh-78"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-78-node"
    pod_subnet_name               = "clustermesh-78-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-79"
    aks_name                      = "clustermesh-79"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-79-node"
    pod_subnet_name               = "clustermesh-79-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-80"
    aks_name                      = "clustermesh-80"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-80-node"
    pod_subnet_name               = "clustermesh-80-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-81"
    aks_name                      = "clustermesh-81"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-81-node"
    pod_subnet_name               = "clustermesh-81-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-82"
    aks_name                      = "clustermesh-82"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-82-node"
    pod_subnet_name               = "clustermesh-82-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-83"
    aks_name                      = "clustermesh-83"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-83-node"
    pod_subnet_name               = "clustermesh-83-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-84"
    aks_name                      = "clustermesh-84"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-84-node"
    pod_subnet_name               = "clustermesh-84-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-85"
    aks_name                      = "clustermesh-85"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-85-node"
    pod_subnet_name               = "clustermesh-85-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-86"
    aks_name                      = "clustermesh-86"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-86-node"
    pod_subnet_name               = "clustermesh-86-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-87"
    aks_name                      = "clustermesh-87"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-87-node"
    pod_subnet_name               = "clustermesh-87-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-88"
    aks_name                      = "clustermesh-88"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-88-node"
    pod_subnet_name               = "clustermesh-88-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-89"
    aks_name                      = "clustermesh-89"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-89-node"
    pod_subnet_name               = "clustermesh-89-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-90"
    aks_name                      = "clustermesh-90"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-90-node"
    pod_subnet_name               = "clustermesh-90-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-91"
    aks_name                      = "clustermesh-91"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-91-node"
    pod_subnet_name               = "clustermesh-91-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-92"
    aks_name                      = "clustermesh-92"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-92-node"
    pod_subnet_name               = "clustermesh-92-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-93"
    aks_name                      = "clustermesh-93"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-93-node"
    pod_subnet_name               = "clustermesh-93-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-94"
    aks_name                      = "clustermesh-94"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-94-node"
    pod_subnet_name               = "clustermesh-94-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-95"
    aks_name                      = "clustermesh-95"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-95-node"
    pod_subnet_name               = "clustermesh-95-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-96"
    aks_name                      = "clustermesh-96"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-96-node"
    pod_subnet_name               = "clustermesh-96-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-97"
    aks_name                      = "clustermesh-97"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-97-node"
    pod_subnet_name               = "clustermesh-97-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-98"
    aks_name                      = "clustermesh-98"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-98-node"
    pod_subnet_name               = "clustermesh-98-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-99"
    aks_name                      = "clustermesh-99"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-99-node"
    pod_subnet_name               = "clustermesh-99-pod"
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
      vm_size              = "Standard_D8_v3"
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
    role                          = "mesh-100"
    aks_name                      = "clustermesh-100"
    sku_tier                      = "Standard"
    subnet_name                   = "clustermesh-100-node"
    pod_subnet_name               = "clustermesh-100-pod"
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
      vm_size              = "Standard_D8_v3"
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
# Fleet + ClusterMesh — shared-VNet mode (no peerings).
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
    { member_name = "mesh-20", aks_role = "mesh-20" },
    { member_name = "mesh-21", aks_role = "mesh-21" },
    { member_name = "mesh-22", aks_role = "mesh-22" },
    { member_name = "mesh-23", aks_role = "mesh-23" },
    { member_name = "mesh-24", aks_role = "mesh-24" },
    { member_name = "mesh-25", aks_role = "mesh-25" },
    { member_name = "mesh-26", aks_role = "mesh-26" },
    { member_name = "mesh-27", aks_role = "mesh-27" },
    { member_name = "mesh-28", aks_role = "mesh-28" },
    { member_name = "mesh-29", aks_role = "mesh-29" },
    { member_name = "mesh-30", aks_role = "mesh-30" },
    { member_name = "mesh-31", aks_role = "mesh-31" },
    { member_name = "mesh-32", aks_role = "mesh-32" },
    { member_name = "mesh-33", aks_role = "mesh-33" },
    { member_name = "mesh-34", aks_role = "mesh-34" },
    { member_name = "mesh-35", aks_role = "mesh-35" },
    { member_name = "mesh-36", aks_role = "mesh-36" },
    { member_name = "mesh-37", aks_role = "mesh-37" },
    { member_name = "mesh-38", aks_role = "mesh-38" },
    { member_name = "mesh-39", aks_role = "mesh-39" },
    { member_name = "mesh-40", aks_role = "mesh-40" },
    { member_name = "mesh-41", aks_role = "mesh-41" },
    { member_name = "mesh-42", aks_role = "mesh-42" },
    { member_name = "mesh-43", aks_role = "mesh-43" },
    { member_name = "mesh-44", aks_role = "mesh-44" },
    { member_name = "mesh-45", aks_role = "mesh-45" },
    { member_name = "mesh-46", aks_role = "mesh-46" },
    { member_name = "mesh-47", aks_role = "mesh-47" },
    { member_name = "mesh-48", aks_role = "mesh-48" },
    { member_name = "mesh-49", aks_role = "mesh-49" },
    { member_name = "mesh-50", aks_role = "mesh-50" },
    { member_name = "mesh-51", aks_role = "mesh-51" },
    { member_name = "mesh-52", aks_role = "mesh-52" },
    { member_name = "mesh-53", aks_role = "mesh-53" },
    { member_name = "mesh-54", aks_role = "mesh-54" },
    { member_name = "mesh-55", aks_role = "mesh-55" },
    { member_name = "mesh-56", aks_role = "mesh-56" },
    { member_name = "mesh-57", aks_role = "mesh-57" },
    { member_name = "mesh-58", aks_role = "mesh-58" },
    { member_name = "mesh-59", aks_role = "mesh-59" },
    { member_name = "mesh-60", aks_role = "mesh-60" },
    { member_name = "mesh-61", aks_role = "mesh-61" },
    { member_name = "mesh-62", aks_role = "mesh-62" },
    { member_name = "mesh-63", aks_role = "mesh-63" },
    { member_name = "mesh-64", aks_role = "mesh-64" },
    { member_name = "mesh-65", aks_role = "mesh-65" },
    { member_name = "mesh-66", aks_role = "mesh-66" },
    { member_name = "mesh-67", aks_role = "mesh-67" },
    { member_name = "mesh-68", aks_role = "mesh-68" },
    { member_name = "mesh-69", aks_role = "mesh-69" },
    { member_name = "mesh-70", aks_role = "mesh-70" },
    { member_name = "mesh-71", aks_role = "mesh-71" },
    { member_name = "mesh-72", aks_role = "mesh-72" },
    { member_name = "mesh-73", aks_role = "mesh-73" },
    { member_name = "mesh-74", aks_role = "mesh-74" },
    { member_name = "mesh-75", aks_role = "mesh-75" },
    { member_name = "mesh-76", aks_role = "mesh-76" },
    { member_name = "mesh-77", aks_role = "mesh-77" },
    { member_name = "mesh-78", aks_role = "mesh-78" },
    { member_name = "mesh-79", aks_role = "mesh-79" },
    { member_name = "mesh-80", aks_role = "mesh-80" },
    { member_name = "mesh-81", aks_role = "mesh-81" },
    { member_name = "mesh-82", aks_role = "mesh-82" },
    { member_name = "mesh-83", aks_role = "mesh-83" },
    { member_name = "mesh-84", aks_role = "mesh-84" },
    { member_name = "mesh-85", aks_role = "mesh-85" },
    { member_name = "mesh-86", aks_role = "mesh-86" },
    { member_name = "mesh-87", aks_role = "mesh-87" },
    { member_name = "mesh-88", aks_role = "mesh-88" },
    { member_name = "mesh-89", aks_role = "mesh-89" },
    { member_name = "mesh-90", aks_role = "mesh-90" },
    { member_name = "mesh-91", aks_role = "mesh-91" },
    { member_name = "mesh-92", aks_role = "mesh-92" },
    { member_name = "mesh-93", aks_role = "mesh-93" },
    { member_name = "mesh-94", aks_role = "mesh-94" },
    { member_name = "mesh-95", aks_role = "mesh-95" },
    { member_name = "mesh-96", aks_role = "mesh-96" },
    { member_name = "mesh-97", aks_role = "mesh-97" },
    { member_name = "mesh-98", aks_role = "mesh-98" },
    { member_name = "mesh-99", aks_role = "mesh-99" },
    { member_name = "mesh-100", aks_role = "mesh-100" }
  ]
}
