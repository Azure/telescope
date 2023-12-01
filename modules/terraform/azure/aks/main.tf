locals {  
  role      = var.aks_config.role
  name      = var.aks_config.aks_name    
}

resource "azurerm_kubernetes_cluster" "aks" {
    name                =  local.name
    location            = var.location
    resource_group_name = var.resource_group_name
    dns_prefix          = var.aks_config.dns_prefix

    default_node_pool {
    name                         = var.aks_config.default_node_pool.name
    node_count                   = var.aks_config.default_node_pool.node_count
    vm_size                      = var.vm_sku
    vnet_subnet_id               = var.subnet_id
    os_disk_type                 = var.aks_config.default_node_pool.os_disk_type
    only_critical_addons_enabled = var.aks_config.default_node_pool.only_critical_addons_enabled
    temporary_name_for_rotation  = var.aks_config.default_node_pool.temporary_name_for_rotation
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
  }  
 identity {
    type = "SystemAssigned"
  }
  
}

resource "azurerm_kubernetes_cluster_node_pool" "pools" {
  for_each = var.aks_config.extra_node_pool

  name                  = each.value.name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  vm_size               = var.vm_sku
  node_count            = each.value.count
  os_disk_type          = var.aks_config.default_node_pool.os_disk_type
}