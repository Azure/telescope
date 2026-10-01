scenario_type  = "perf-eval"
scenario_name  = "vmagent-loadtest"
# This scenario is reused as a PERSISTENT BYO cluster pair across many
# pipeline runs over weeks (SKIP_RESOURCE_MANAGEMENT=true + fixed
# run_id="vmagent-loadtesting", see pipelines/perf-eval/Vmagent Benchmark/
# vmagent-loadtest.yml) -- NOT per-run ephemeral infra. The 10h value this
# scenario was originally created with let Telescope's external GC reaper
# (which enforces the deletion_due_time tag regardless of
# SKIP_RESOURCE_MANAGEMENT) delete both CP and DP clusters ~40 days after
# creation, once it caught up to the long-overdue tag. Azure's
# deletion_delay has no enforced max (unlike AWS's 72h cap) -- set to 1
# year here so the reaper leaves this pair alone for the long term.
deletion_delay = "8760h"
owner          = "aks"

aks_config_list = [
  {
    role        = "cp"
    aks_name    = "vmagent-cp"
    dns_prefix  = "vmagent-cp"
    subnet_name = "cp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "default"
      node_count                   = 2
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D4_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = [
      {
        name                 = "controlplane"
        node_count           = 9
        auto_scaling_enabled = false
        vm_size              = "Standard_D4_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
      }
    ]
  },
  {
    role        = "dp"
    aks_name    = "vmagent-dp"
    dns_prefix  = "vmagent-dp"
    subnet_name = "dp-subnet"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      # 100.64.0.0/10 (CGNAT space): avoids the default AKS service_cidr
      # (10.0.0.0/16), the 10.224.0.0/12 VNet, and the AKS-reserved ranges
      # (172.30/16, 172.31/16, 169.254/16, 192.0.2/24, 224.0.0.0/4).
      # 172.16.0.0/12 was rejected after AKS tightened pod-CIDR overlap
      # validation. /10 gives 16k /24 node blocks — ample for 5K+ nodes.
      # Same choice as the cnl-azurecni-overlay-cilium scenario.
      pod_cidr = "100.64.0.0/10"
    }
    default_node_pool = {
      name                         = "nodepool1"
      node_count                   = 2
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D2_v3"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
      max_pods                     = 250
    }
    extra_node_pool = [
      {
        name                 = "dataplane"
        node_count           = 1
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
      },
      # Fixed tier-block pools (see config.TIER_BLOCK_REGEX) -- permanent,
      # never scaled/deleted per run; --fixed-pools selects tiers via scrape
      # regex instead. dpagentpool is a dedicated, tainted pool for agents.
      {
        name                 = "dpblocka"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
        node_labels = {
          "loadtest.io/tier-block" = "a"
        }
      },
      {
        name                 = "dpblockb"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
        node_labels = {
          "loadtest.io/tier-block" = "b"
        }
      },
      {
        name                 = "dpblockc"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
        node_labels = {
          "loadtest.io/tier-block" = "c"
        }
      },
      {
        name                 = "dpblockd"
        node_count           = 500
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
        node_labels = {
          "loadtest.io/tier-block" = "d"
        }
      },
      {
        name                 = "dpagentpool"
        node_count           = 10
        auto_scaling_enabled = false
        vm_size              = "Standard_D2_v3"
        os_disk_type         = "Managed"
        max_pods             = 250
        node_labels = {
          "loadtest.io/role" = "konn-agent"
        }
        node_taints = ["dedicated=konn-agent:NoSchedule"]
      }
    ]
  }
]
