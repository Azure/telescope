locals {
  role                 = var.aks_config.role
  name                 = var.aks_config.aks_name
  extra_pool_map       = { for pool in var.aks_config.extra_node_pool : pool.name => pool }
  role_assignment_list = var.aks_config.role_assignment_list
  subnets              = var.subnets
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = local.name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.aks_config.dns_prefix
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
  sku_tier = var.aks_config.sku_tier
  default_node_pool {
    name                         = var.aks_config.default_node_pool.name
    node_count                   = var.aks_config.default_node_pool.node_count
    vm_size                      = var.aks_config.default_node_pool.vm_size
    vnet_subnet_id               = try(local.subnets[var.aks_config.default_node_pool.subnet_name], try(var.subnet_id, null))
    os_sku                       = var.aks_config.default_node_pool.os_sku
    os_disk_type                 = var.aks_config.default_node_pool.os_disk_type
    only_critical_addons_enabled = var.aks_config.default_node_pool.only_critical_addons_enabled
    temporary_name_for_rotation  = var.aks_config.default_node_pool.temporary_name_for_rotation
    max_pods                     = var.aks_config.default_node_pool.max_pods
    enable_auto_scaling          = var.aks_config.default_node_pool.enable_auto_scaling
    min_count                    = var.aks_config.default_node_pool.enable_auto_scaling ? var.aks_config.default_node_pool.min_count : null
    max_count                    = var.aks_config.default_node_pool.enable_auto_scaling ? var.aks_config.default_node_pool.max_count : null
  }

  dynamic "auto_scaler_profile" {
    for_each = try(var.aks_config.auto_scaler_profile != null ? [var.aks_config.auto_scaler_profile] : [])

    content {
      balance_similar_node_groups      = try(auto_scaler_profile.balance_similar_node_groups, null) # Default to null if not provided
      expander                         = try(auto_scaler_profile.expander, null)
      max_graceful_termination_sec     = try(auto_scaler_profile.max_graceful_termination_sec, null)
      max_node_provisioning_time       = try(auto_scaler_profile.max_node_provisioning_time, null)
      max_unready_nodes                = try(auto_scaler_profile.max_unready_nodes, null)
      max_unready_percentage           = try(auto_scaler_profile.max_unready_percentage, null)
      new_pod_scale_up_delay           = try(auto_scaler_profile.new_pod_scale_up_delay, null)
      scale_down_delay_after_add       = try(auto_scaler_profile.scale_down_delay_after_add, null)
      scale_down_delay_after_delete    = try(auto_scaler_profile.scale_down_delay_after_delete, null)
      scale_down_delay_after_failure   = try(auto_scaler_profile.scale_down_delay_after_failure, null)
      scan_interval                    = try(auto_scaler_profile.scan_interval, null)
      scale_down_unneeded              = try(auto_scaler_profile.scale_down_unneeded, null)
      scale_down_unready               = try(auto_scaler_profile.scale_down_unready, null)
      scale_down_utilization_threshold = try(auto_scaler_profile.scale_down_utilization_threshold, null)
      empty_bulk_delete_max            = try(auto_scaler_profile.empty_bulk_delete_max, null)
      skip_nodes_with_local_storage    = try(auto_scaler_profile.skip_nodes_with_local_storage, null)
      skip_nodes_with_system_pods      = try(auto_scaler_profile.skip_nodes_with_system_pods, null)
    }
  }


  network_profile {
    network_plugin      = var.aks_config.network_profile.network_plugin
    network_plugin_mode = var.aks_config.network_profile.network_plugin_mode
    network_policy      = var.aks_config.network_profile.network_policy
    ebpf_data_plane     = var.aks_config.network_profile.ebpf_data_plane
    outbound_type       = var.aks_config.network_profile.outbound_type
    pod_cidr            = var.aks_config.network_profile.pod_cidr
  }
  identity {
    type = "SystemAssigned"
  }

  dynamic "service_mesh_profile" {
    for_each = try(var.aks_config.service_mesh_profile != null ? [var.aks_config.service_mesh_profile] : [])
    content {
      mode = service_mesh_profile.value.mode
    }
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  lifecycle {
    ignore_changes = [default_node_pool[0].node_count]
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "pools" {
  for_each = local.extra_pool_map

  name                  = each.value.name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  node_count            = each.value.node_count
  vm_size               = each.value.vm_size
  vnet_subnet_id        = try(local.subnets[each.value.subnet_name], null)
  os_sku                = each.value.os_sku
  os_disk_type          = each.value.os_disk_type
  max_pods              = each.value.max_pods
  ultra_ssd_enabled     = try(each.value.ultra_ssd_enabled, false)
  zones                 = try(each.value.zones, [])
  enable_auto_scaling   = each.value.enable_auto_scaling
  min_count             = each.value.enable_auto_scaling ? each.value.min_count : null
  max_count             = each.value.enable_auto_scaling ? each.value.max_count : null
}

resource "azurerm_role_assignment" "aks_on_subnet" {
  for_each = toset(local.role_assignment_list)

  role_definition_name = each.key
  scope                = var.vnet_id
  principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
}

resource "local_file" "kube_config" {
  filename = "/tmp/${azurerm_kubernetes_cluster.aks.fqdn}"
  content  = azurerm_kubernetes_cluster.aks.kube_config_raw
}
