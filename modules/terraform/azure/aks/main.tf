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
  }

  network_profile {
    network_plugin      = var.aks_config.network_profile.network_plugin
    network_plugin_mode = var.aks_config.network_profile.network_plugin_mode
    network_policy      = var.aks_config.network_profile.network_policy
    outbound_type       = var.aks_config.network_profile.outbound_type
    pod_cidr            = var.aks_config.network_profile.pod_cidr
  }
  identity {
    type = "SystemAssigned"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true
}

resource "azurerm_kubernetes_cluster_node_pool" "pools" {
  for_each = local.extra_pool_map

  name                  = each.value.name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  node_count            = each.value.node_count
  vnet_subnet_id        = try(local.subnets[each.value.subnet_name], null)
  vm_size               = each.value.vm_size
  os_sku                = each.value.os_sku
  os_disk_type          = each.value.os_disk_type
  max_pods              = each.value.max_pods
  zones                 = try(each.value.zones, [])
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

provider "helm" {
  kubernetes {
    config_path = local_file.kube_config.filename
  }
}

resource "helm_release" "vn2" {
  name       = "vn2"
  chart      = "https://shuvstorageaccount.blob.core.windows.net/mycontainer/virtualnode2-0.0.1.tgz"

  namespace        = "vn2-namespace"
  create_namespace = true  

  depends_on = [azurerm_kubernetes_cluster.aks]
}
