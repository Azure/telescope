locals {
  tags = {
    "owner"         = lookup(var.json_input, "owner", "github_actions")
    "scenario"      = "${var.json_input.scenario_type}-${var.json_input.scenario_name}-${var.json_input.scenario_version}"
    "creation_time" = timestamp()
    "run_id"        = lookup(var.json_input, "run_id", "github_actions")
  }
  formatted_scenario_name = "${var.json_input.scenario_type}-${var.json_input.scenario_name}-${var.json_input.scenario_version}"
}
provider "azurerm" {
  features {}
}


# Resource Group
data "azurerm_resource_group" "rg" {
  name = var.json_input.resource_group_name
}

# Storage Account
data "azurerm_storage_account" "storage" {
  name                = var.json_input.storage_account_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Storage Container
data "azurerm_storage_container" "container" {
  name                 = var.json_input.scenario_type
  storage_account_name = data.azurerm_storage_account.storage.name
}

data "azurerm_kusto_cluster" "cluster" {
  name                = var.json_input.kusto_cluster_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Azure Data Explorer Database
data "azurerm_kusto_database" "database" {
  name                = var.json_input.kusto_database_name
  resource_group_name = data.azurerm_resource_group.rg.name
  cluster_name        = data.azurerm_kusto_cluster.cluster.name
}

resource "azurerm_kusto_script" "script" {
  name                               = "kusto-script-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  database_id                        = data.azurerm_kusto_database.database.id
  continue_on_errors_enabled         = false
  force_an_update_when_value_changed = "first"
  script_content                     = base64decode(var.json_input.table_creation_script)
}

data "azurerm_eventhub_namespace" "eventhub_ns" {
  name                = var.json_input.eventhub_namespace_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_eventhub" "eventhub" {
  name                = local.formatted_scenario_name
  namespace_name      = data.azurerm_eventhub_namespace.eventhub_ns.name
  resource_group_name = data.azurerm_resource_group.rg.name
  partition_count     = 8
  message_retention   = 7
}

resource "azurerm_eventhub_consumer_group" "consumer_group" {
  name                = "default"
  namespace_name      = data.azurerm_eventhub_namespace.eventhub_ns.name
  eventhub_name       = azurerm_eventhub.eventhub.name
  resource_group_name = data.azurerm_resource_group.rg.name
}

data "azurerm_eventgrid_system_topic" "topic" {
  name                = var.json_input.eventgrid_topic_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_eventgrid_system_topic_event_subscription" "event_subscription" {
  name                  = local.formatted_scenario_name
  system_topic          = data.azurerm_eventgrid_system_topic.topic.name
  resource_group_name   = data.azurerm_resource_group.rg.name
  event_delivery_schema = "EventGridSchema"
  eventhub_endpoint_id  = azurerm_eventhub.eventhub.id
  included_event_types  = ["Microsoft.Storage.BlobCreated"]
  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${var.json_input.scenario_type}/blobs/${var.json_input.scenario_name}/${var.json_input.scenario_version}"
  }
  advanced_filtering_on_arrays_enabled = true
  depends_on                           = [data.azurerm_storage_container.container]
}

resource "azurerm_kusto_eventgrid_data_connection" "evengrid_connection" {
  name                         = local.formatted_scenario_name
  resource_group_name          = data.azurerm_resource_group.rg.name
  location                     = data.azurerm_resource_group.rg.location
  cluster_name                 = data.azurerm_kusto_cluster.cluster.name
  database_name                = data.azurerm_kusto_database.database.name
  storage_account_id           = data.azurerm_storage_account.storage.id
  eventhub_id                  = azurerm_eventhub.eventhub.id
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumer_group.name
  managed_identity_resource_id = data.azurerm_kusto_cluster.cluster.id
  table_name                   = var.json_input.kusto_table_name
  data_format                  = "JSON"
  mapping_rule_name            = "${var.json_input.kusto_table_name}_mapping"
  depends_on                   = [azurerm_eventgrid_system_topic_event_subscription.event_subscription]
}