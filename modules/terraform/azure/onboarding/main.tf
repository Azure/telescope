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
  count    = length(data.azurerm_resource_group.rg) == 0 ? 1 : 0
  name     = var.json_input.resource_group_name
  location = "eastus"
  tags     = local.tags
}

data "azurerm_resource_group" "rg" {
  name = var.json_input.resource_group_name
}

# Storage Account
resource "azurerm_storage_account" "storage" {
  count                    = length(data.azurerm_storage_account.storage) == 0 ? 1 : 0
  name                     = var.json_input.storage_account_name
  resource_group_name      = azurerm_resource_group.rg[0].name
  location                 = azurerm_resource_group.rg[0].location
  account_tier             = "Standard"
  account_replication_type = "RA-GRS"
  tags                     = local.tags
}

data "azurerm_storage_account" "storage" {
  name                = var.json_input.storage_account_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Storage Container
resource "azurerm_storage_container" "container" {
  count                = length(data.azurerm_storage_container.container) == 0 ? 1 : 0
  name                 = var.json_input.scenario_type
  storage_account_name = azurerm_storage_account.storage[0].name
}

data "azurerm_storage_container" "container" {
  name                 = var.json_input.scenario_type
  storage_account_name = data.azurerm_storage_account.storage.name
}

# Kusto Cluster
resource "azurerm_kusto_cluster" "cluster" {
  count               = length(data.azurerm_kusto_cluster.cluster) == 0 ? 1 : 0
  name                = var.json_input.kusto_cluster_name
  resource_group_name = azurerm_resource_group.rg[0].name
  location            = azurerm_resource_group.rg[0].location
  sku {
    name     = "Standard_E16ads_v5"
    capacity = 2
  }
  tags = local.tags
}

data "azurerm_kusto_cluster" "cluster" {
  name                = var.json_input.kusto_cluster_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Kusto Database
resource "azurerm_kusto_database" "database" {
  count               = length(data.azurerm_kusto_database.database) == 0 ? 1 : 0
  name                = var.json_input.kusto_database_name
  resource_group_name = azurerm_resource_group.rg[0].name
  cluster_name        = azurerm_kusto_cluster.cluster[0].name
  location            = azurerm_resource_group.rg[0].location
}

data "azurerm_kusto_database" "database" {
  name                = var.json_input.kusto_database_name
  resource_group_name = data.azurerm_resource_group.rg.name
  cluster_name        = data.azurerm_kusto_cluster.cluster.name
}

# Event Hub Namespace
resource "azurerm_eventhub_namespace" "eventhub_ns" {
  count               = var.json_input.create_eventhub_namespace ? length(data.azurerm_eventhub_namespace.eventhub_ns) == 0 ? 1 : 0 : 0
  name                = var.json_input.eventhub_namespace_name
  resource_group_name = azurerm_resource_group.rg[0].name
  location            = azurerm_resource_group.rg[0].location
  sku                 = "Standard"
  capacity            = 1
  tags                = local.tags
}

data "azurerm_eventhub_namespace" "eventhub_ns" {
  name                = var.json_input.eventhub_namespace_name
  count               = var.json_input.create_eventhub_namespace ? 1 : 0
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Event Hub
resource "azurerm_eventhub" "eventhub" {
  name                = "adx-eg-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  namespace_name      = var.json_input.create_eventhub_namespace ? azurerm_eventhub_namespace.eventhub_ns[0].name : data.azurerm_eventhub_namespace.eventhub_ns[0].name
  resource_group_name = azurerm_resource_group.rg[0].name
  partition_count     = 8
  message_retention   = 7
}

# Role Assignment
resource "azurerm_role_assignment" "eventhub_role_assignment" {
  scope                = azurerm_eventhub.eventhub.id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = azurerm_kusto_cluster.cluster[0].identity[0].principal_id
}

# Event Hub Consumer Group
resource "azurerm_eventhub_consumer_group" "consumer_group" {
  name                = "default"
  namespace_name      = var.json_input.create_eventhub_namespace ? azurerm_eventhub_namespace.eventhub_ns[0].name : data.azurerm_eventhub_namespace.eventhub_ns[0].name
  eventhub_name       = azurerm_eventhub.eventhub.name
  resource_group_name = azurerm_resource_group.rg[0].name
}

# Event Grid Event Subscription
resource "azurerm_eventgrid_event_subscription" "event_subscription" {
  name                  = "ADX-EG-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  scope                 = azurerm_storage_account.storage[0].id
  event_delivery_schema = "EventGridSchema"
  eventhub_endpoint_id  = azurerm_eventhub.eventhub.id
  included_event_types  = ["Microsoft.Storage.BlobCreated"]
  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${var.json_input.scenario_type}/blobs/${var.json_input.scenario_name}/${var.json_input.scenario_version}"
  }
  advanced_filtering_on_arrays_enabled = true
  depends_on                           = [azurerm_storage_container.container]
}

# Kusto Event Grid Data Connection
resource "azurerm_kusto_eventgrid_data_connection" "evengrid_connection" {
  name                         = var.json_input.data_connection_name
  resource_group_name          = azurerm_resource_group.rg[0].name
  location                     = azurerm_resource_group.rg[0].location
  cluster_name                 = azurerm_kusto_cluster.cluster[0].name
  database_name                = azurerm_kusto_database.database[0].name
  storage_account_id           = azurerm_storage_account.storage[0].id
  blob_storage_event_type      = "Microsoft.Storage.BlobCreated"
  eventgrid_resource_id        = azurerm_eventgrid_event_subscription.event_subscription.id
  eventhub_id                  = azurerm_eventhub.eventhub.id
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumer_group[0].name
  managed_identity_resource_id = azurerm_kusto_cluster.cluster[0].id
  database_routing_type        = "Single"
  table_name                   = var.json_input.kusto_table_name
  data_format                  = "JSON"
  mapping_rule_name            = "${var.json_input.kusto_table_name}_mapping"
  depends_on                   = [azurerm_eventgrid_event_subscription.event_subscription, azurerm_kusto_script.script, azurerm_eventhub_consumer_group.consumer_group]
}
