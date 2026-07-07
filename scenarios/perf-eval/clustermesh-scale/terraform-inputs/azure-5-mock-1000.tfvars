scenario_type  = "perf-eval"
scenario_name  = "clustermesh-scale"
deletion_delay = "6h"
owner          = "aks"

# =============================================================================
# ClusterMesh Scale Test — 5 clusters x 1000 virtual nodes — MOCK variant
#
# The SHARDED side of the consolidated-vs-sharded comparison: 5 clusters x 1000
# KWOK virtual nodes + mock-cilium-agents = 5000 total nodes, same as the 1x5000
# single-cluster baseline, so 1x5000 vs 5x1000 is a fair same-total comparison
# (workload also split: 5000/N pods per cluster). Each cluster's apiserver bears
# only 1000 agents (well below the ~5-7k single-cluster ceiling) + the ClusterMesh
# fan-out. Uses the >250-nodes/cluster mesh podCIDR scheme (MOCK_MESH_STRIDE set in
# the stage) so Pod/node IPs stay unique ACROSS the mesh.
#
# Per cluster: 7 x Standard_D32_v3 default pool (hosts 1000 mock-agent Pods) +
# 1 x Standard_D16_v3 prompool (per-cluster Prometheus). Separate VNets (10.<id>.0.0/16)
# + pairwise peering + Fleet ClusterMesh (mesh-1..mesh-5).
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
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~1000
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
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~1000
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
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~1000
        # mock-agent Pods a real IP; the churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 CIDRs), NOT this subnet.
        name           = "clustermesh-3-pod"
        address_prefix = "10.3.32.0/19"
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
    role               = "mesh-4"
    vnet_name          = "clustermesh-4-vnet"
    vnet_address_space = "10.4.0.0/16"
    subnet = [
      {
        name           = "clustermesh-4-node"
        address_prefix = "10.4.0.0/24"
      },
      {
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~1000
        # mock-agent Pods a real IP; the churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 CIDRs), NOT this subnet.
        name           = "clustermesh-4-pod"
        address_prefix = "10.4.32.0/19"
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
    role               = "mesh-5"
    vnet_name          = "clustermesh-5-vnet"
    vnet_address_space = "10.5.0.0/16"
    subnet = [
      {
        name           = "clustermesh-5-node"
        address_prefix = "10.5.0.0/24"
      },
      {
        # /19 (8190 IPs) — Azure CNI (pod subnet) gives every one of the ~1000
        # mock-agent Pods a real IP; the churn workload runs on KWOK virtual
        # nodes (synthetic 100.0.0.0/8 CIDRs), NOT this subnet.
        name           = "clustermesh-5-pod"
        address_prefix = "10.5.32.0/19"
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
      # Azure CNI w/ pod subnet supports up to 250. 1000 agents / 250 = 4 nodes floor;
      # the 7-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 1000 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 7 x Standard_D32_v3 = 224 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 7
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 1000 agents (~0.9M series / a few GiB), so 64 GiB is ample.
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
      # Azure CNI w/ pod subnet supports up to 250. 1000 agents / 250 = 4 nodes floor;
      # the 7-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 1000 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 7 x Standard_D32_v3 = 224 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 7
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 1000 agents (~0.9M series / a few GiB), so 64 GiB is ample.
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
      # Azure CNI w/ pod subnet supports up to 250. 1000 agents / 250 = 4 nodes floor;
      # the 7-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 1000 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 7 x Standard_D32_v3 = 224 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 7
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 1000 agents (~0.9M series / a few GiB), so 64 GiB is ample.
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
      # Azure CNI w/ pod subnet supports up to 250. 1000 agents / 250 = 4 nodes floor;
      # the 7-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 1000 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 7 x Standard_D32_v3 = 224 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 7
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 1000 agents (~0.9M series / a few GiB), so 64 GiB is ample.
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
      # Azure CNI w/ pod subnet supports up to 250. 1000 agents / 250 = 4 nodes floor;
      # the 7-node pool below leaves headroom for system daemonsets.
      { name = "max-pods", value = "250" },
    ]

    # Default pool hosts the 1000 mock-cilium-agent Pods (real pods, ~9m CPU/56Mi
    # each measured). 7 x Standard_D32_v3 = 224 vCPU. Agents avoid the
    # prometheus=true prompool via nodeAffinity (provision-kwok-layer.sh).
    default_node_pool = {
      name                 = "default"
      node_count           = 7
      auto_scaling_enabled = false
      vm_size              = "Standard_D32_v3"
    }
    # Per-cluster Prometheus node (label prometheus=true; CL2 pins prometheus-k8s
    # here). Standard_D16_v3 = 64 GiB — this cluster's Prometheus scrapes only its own
    # 1000 agents (~0.9M series / a few GiB), so 64 GiB is ample.
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
    { member_name = "mesh-2", aks_role = "mesh-2" },
    { member_name = "mesh-3", aks_role = "mesh-3" },
    { member_name = "mesh-4", aks_role = "mesh-4" },
    { member_name = "mesh-5", aks_role = "mesh-5" }
  ]
}
