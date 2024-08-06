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
}

# Resource Group
resource "azurerm_resource_group" "rg" {
  name     = var.json_input.resource_group_name
  location = var.json_input.location
  tags     = local.tags
}


# Storage Account
resource "azurerm_storage_account" "storage" {
  name                     = var.json_input.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "RA-GRS"
  tags                     = local.tags
}


# Storage Container
resource "azurerm_storage_container" "container" {
  name                 = var.json_input.scenario_type
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
  tags = local.tags
}

# Kusto Database
resource "azurerm_kusto_database" "database" {
  name                = var.json_input.kusto_database_name
  resource_group_name = azurerm_resource_group.rg.name
  cluster_name        = azurerm_kusto_cluster.cluster.name
  location            = azurerm_resource_group.rg.location
}
