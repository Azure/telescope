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
    vm_size                      = coalesce(var.k8s_machine_type, var.aks_config.default_node_pool.vm_size)
    vnet_subnet_id               = try(local.subnets[var.aks_config.default_node_pool.subnet_name], try(var.subnet_id, null))
    os_sku                       = var.aks_config.default_node_pool.os_sku
    os_disk_type                 = coalesce(var.k8s_os_disk_type, var.aks_config.default_node_pool.os_disk_type)
    os_disk_size_gb              = var.aks_config.default_node_pool.os_disk_size_gb
    only_critical_addons_enabled = var.aks_config.default_node_pool.only_critical_addons_enabled
    temporary_name_for_rotation  = var.aks_config.default_node_pool.temporary_name_for_rotation
    max_pods                     = var.aks_config.default_node_pool.max_pods
    node_labels                  = var.aks_config.default_node_pool.node_labels
  }

  network_profile {
    network_plugin      = var.aks_config.network_profile.network_plugin
    network_plugin_mode = var.aks_config.network_profile.network_plugin_mode
    network_policy      = try(coalesce(var.network_policy, var.aks_config.network_profile.network_policy), null)
    network_data_plane  = try(coalesce(var.network_dataplane, var.aks_config.network_profile.network_dataplane), null)
    outbound_type       = var.aks_config.network_profile.outbound_type
    pod_cidr            = var.aks_config.network_profile.pod_cidr
    service_cidr        = var.aks_config.network_profile.service_cidr
    dns_service_ip      = var.aks_config.network_profile.dns_service_ip
  }
  identity {
    type = "SystemAssigned"
  }

  dynamic "service_mesh_profile" {
    for_each = try(var.aks_config.service_mesh_profile != null ? [var.aks_config.service_mesh_profile] : [])
    content {
      mode      = service_mesh_profile.value.mode
      revisions = service_mesh_profile.value.revisions
    }
  }

  dynamic "auto_scaler_profile" {
    for_each = try(var.aks_config.auto_scaler_profile != null ? [var.aks_config.auto_scaler_profile] : [])
    content {
      balance_similar_node_groups      = auto_scaler_profile.value.balance_similar_node_groups
      expander                         = auto_scaler_profile.value.expander
      max_graceful_termination_sec     = auto_scaler_profile.value.max_graceful_termination_sec
      max_node_provisioning_time       = auto_scaler_profile.value.max_node_provisioning_time
      max_unready_nodes                = auto_scaler_profile.value.max_unready_nodes
      max_unready_percentage           = auto_scaler_profile.value.max_unready_percentage
      new_pod_scale_up_delay           = auto_scaler_profile.value.new_pod_scale_up_delay
      scale_down_delay_after_add       = auto_scaler_profile.value.scale_down_delay_after_add
      scale_down_delay_after_delete    = auto_scaler_profile.value.scale_down_delay_after_delete
      scale_down_delay_after_failure   = auto_scaler_profile.value.scale_down_delay_after_failure
      scan_interval                    = auto_scaler_profile.value.scan_interval
      scale_down_unneeded              = auto_scaler_profile.value.scale_down_unneeded
      scale_down_unready               = auto_scaler_profile.value.scale_down_unready
      scale_down_utilization_threshold = auto_scaler_profile.value.scale_down_utilization_threshold
      empty_bulk_delete_max            = auto_scaler_profile.value.empty_bulk_delete_max
      skip_nodes_with_local_storage    = auto_scaler_profile.value.skip_nodes_with_local_storage
      skip_nodes_with_system_pods      = auto_scaler_profile.value.skip_nodes_with_system_pods
    }
  }

  oidc_issuer_enabled       = var.aks_config.oidc_issuer_enabled
  workload_identity_enabled = var.aks_config.workload_identity_enabled
  kubernetes_version        = var.aks_config.kubernetes_version
  edge_zone                 = var.aks_config.edge_zone
  
  dynamic "web_app_routing" {
    for_each = try(var.aks_config.web_app_routing != null ? [var.aks_config.web_app_routing] : [])
    content {
      dns_zone_ids = var.aks_config.web_app_routing.dns_zone_ids
    }
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "aks_node_pools" {
  for_each = local.extra_pool_map

  name                  = each.value.name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  node_count            = each.value.node_count
  vm_size               = coalesce(var.k8s_machine_type, each.value.vm_size)
  vnet_subnet_id        = try(local.subnets[each.value.subnet_name], null)
  os_sku                = each.value.os_sku
  os_disk_type          = coalesce(var.k8s_os_disk_type, each.value.os_disk_type)
  os_disk_size_gb       = each.value.os_disk_size_gb
  max_pods              = each.value.max_pods
  ultra_ssd_enabled     = try(each.value.ultra_ssd_enabled, false)
  zones                 = try(each.value.zones, [])
  node_taints           = each.value.node_taints
  node_labels           = each.value.node_labels
  min_count             = try(each.value.min_count, null)
  max_count             = try(each.value.max_count, null)
  auto_scaling_enabled  = try(each.value.auto_scaling_enabled, false)
}

resource "azurerm_role_assignment" "aks_on_subnet" {
  for_each = toset(local.role_assignment_list)

  role_definition_name = each.key
  scope                = var.vnet_id
  principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
}

resource "local_file" "save_kube_config" {
  filename = "/tmp/${azurerm_kubernetes_cluster.aks.fqdn}"
  content  = azurerm_kubernetes_cluster.aks.kube_config_raw
}
