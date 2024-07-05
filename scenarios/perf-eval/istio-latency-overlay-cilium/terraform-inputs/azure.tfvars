scenario_type  = "perf-eval"
scenario_name  = "istio-latency-overlay-cilium"
deletion_delay = "24h"
aks_config_list = [
  {
    role        = "overlaycilium"
    aks_name    = "istio-overlay-cilium"
    dns_prefix  = "istio-perf-overlay-cilium"
    subnet_name = "aks-network"
    sku_tier    = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
      network_policy      = "cilium"
      ebpf_data_plane     = "cilium"
      pod_cidr            = "192.0.0.0/8"
    }
    default_node_pool = {
      name                         = "npcilium"
      node_count                   = 5
      vm_size                      = "Standard_D16_v5"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "defaulttmp"
    }
    service_mesh_profile = {
      mode = "Istio"
    }
    extra_node_pool = [
      {
        name       = "userpool"
        node_count = 25
        vm_size    = "Standard_D16_v5"
        max_pods   = 250
      }
    ]
  },
]
