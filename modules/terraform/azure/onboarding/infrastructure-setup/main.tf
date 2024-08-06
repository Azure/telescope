provider "azurerm" {
  features {}
  storage_use_azuread = true
}

# Locals for tags
locals {
  tags = {
    owner  = var.json_input.owner
    run_id = var.json_input.run_id
  }
  database_names = var.json_input.kusto_database_names
}

# Resource Group
resource "azurerm_resource_group" "rg" {
  name     = var.json_input.resource_group_name
  location = var.json_input.location
  tags     = local.tags
}

# Managed Identity
resource "azurerm_user_assigned_identity" "mi" {
  name                = "telescope-identity"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

# Role Assignment
resource "azurerm_role_assignment" "owner_role_assignment" {
  role_definition_name = "owner"
  scope                = azurerm_resource_group.rg.id
  principal_id         = azurerm_user_assigned_identity.mi.principal_id
}

# Storage Account
resource "azurerm_storage_account" "storage" {
  name                      = var.json_input.storage_account_name
  resource_group_name       = azurerm_resource_group.rg.name
  location                  = azurerm_resource_group.rg.location
  account_tier              = "Standard"
  account_replication_type  = "RAGRS"
  shared_access_key_enabled = false
  tags                      = local.tags
}

# Role Assignment
resource "azurerm_role_assignment" "blob_contributor_role_assignment" {
  role_definition_name = "Storage Blob Data Contributor"
  scope                = azurerm_storage_account.storage.id
  principal_id         = azurerm_user_assigned_identity.mi.principal_id
}

# Storage Container
resource "azurerm_storage_container" "container" {
  count                = length(local.database_names)
  name                 = local.database_names[count.index]
  storage_account_name = azurerm_storage_account.storage.name
}


# Kusto Cluster
resource "azurerm_kusto_cluster" "cluster" {
  name                = var.json_input.kusto_cluster_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku {
    name     = "Standard_E16ads_v5"
    capacity = 2
  }
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# Role Assignment
resource "azurerm_role_assignment" "storage_role_assignment" {
  scope                = azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_kusto_cluster.cluster.identity[0].principal_id
}

# Kusto Database
resource "azurerm_kusto_database" "database" {
  count               = length(local.database_names)
  name                = local.database_names[count.index]
  resource_group_name = azurerm_resource_group.rg.name
  cluster_name        = azurerm_kusto_cluster.cluster.name
  location            = azurerm_resource_group.rg.location
  hot_cache_period    = "P31D"
  soft_delete_period  = "P365D"
}
