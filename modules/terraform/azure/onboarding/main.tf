provider "azurerm" {
  features {}
}

# Resource Group
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

# Storage Account
data "azurerm_storage_account" "storage" {
  name                = var.storage_account_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Storage Container
resource "azurerm_storage_container" "container" {
  name                  = var.storage_container_name
  storage_account_name  = data.azurerm_storage_account.storage.name
  container_access_type = "private"
}

resource "azurerm_storage_blob" "blob" {
  name                   = "script.txt"
  storage_account_name   = data.azurerm_storage_account.storage.name
  storage_container_name = azurerm_storage_container.container.name
  type                   = "Block"
  source_content         = var.table_creation_script
}

data "azurerm_storage_account_blob_container_sas" "sas" {
  connection_string = data.azurerm_storage_account.storage.primary_connection_string
  container_name    = azurerm_storage_container.container.name
  https_only        = true

  start  = formatdate("YYYY-MM-DD", timestamp())
  expiry = formatdate("YYYY-MM-DD", timestamp() + 86400)

  permissions {
    read   = true
    add    = false
    create = false
    write  = true
    delete = false
    list   = true
  }
}

data "azurerm_kusto_cluster" "cluster" {
  name                = var.kusto_cluster_name
  resource_group_name = data.azurerm_resource_group.rg.name
}


# Azure Data Explorer Database
data "azurerm_kusto_database" "database" {
  name                = var.kusto_database_name
  resource_group_name = data.azurerm_resource_group.rg.name
  cluster_name        = data.azurerm_kusto_cluster.cluster.name
}

resource "azurerm_kusto_script" "script" {
  name                               = "kusto"
  database_id                        = data.azurerm_kusto_database.database.id
  url                                = azurerm_storage_blob.blob.id
  sas_token                          = data.azurerm_storage_account_blob_container_sas.sas.sas
  continue_on_errors_enabled         = true
  force_an_update_when_value_changed = "first"
}


data "azurerm_eventhub_namespace" "eventhub_ns" {
  name                = var.eventhub_namespace_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_eventhub" "eventhub" {
  name                = var.eventhub_name
  namespace_name      = data.azurerm_eventhub_namespace.eventhub_ns.name
  resource_group_name = data.azurerm_resource_group.rg.name
  partition_count     = 8
  message_retention   = 7
}

# data "azuread_service_principal" "kusto_sp" {
#   display_name = var.kusto_cluster_name
# }

# resource "azurerm_role_assignment" "storage_role_assignment" {
#   scope                = data.azurerm_storage_account.storage.id
#   role_definition_name = "Storage Blob Data Contributor"
#   principal_id         = data.azuread_service_principal.kusto_sp.object_id
# }

resource "azurerm_eventhub_consumer_group" "consumer_group" {
  name                = "default"
  namespace_name      = data.azurerm_eventhub_namespace.eventhub_ns.name
  eventhub_name       = azurerm_eventhub.eventhub.name
  resource_group_name = data.azurerm_resource_group.rg.name
}

data "azurerm_eventgrid_system_topic" "topic" {
  name                = var.eventgrid_topic_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_eventgrid_system_topic_event_subscription" "example" {
  name                  = var.eventgrid_subscription_name
  system_topic          = data.azurerm_eventgrid_system_topic.topic.name
  resource_group_name   = data.azurerm_resource_group.rg.name
  event_delivery_schema = "EventGridSchema"
  eventhub_endpoint_id  = azurerm_eventhub.eventhub.id
  included_event_types  = ["Microsoft.Storage.BlobCreated"]
  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${var.storage_container_name}/blobs/sumanth-test"
  }
  advanced_filtering_on_arrays_enabled = true
  depends_on                           = [azurerm_storage_container.container]
}


resource "azurerm_kusto_eventgrid_data_connection" "evengrid_connection" {
  name                         = var.data_connection_name
  resource_group_name          = data.azurerm_resource_group.rg.name
  location                     = data.azurerm_resource_group.rg.location
  cluster_name                 = data.azurerm_kusto_cluster.cluster.name
  database_name                = data.azurerm_kusto_database.database.name
  storage_account_id           = data.azurerm_storage_account.storage.id
  eventhub_id                  = azurerm_eventhub.eventhub.id
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumer_group.name
  managed_identity_resource_id = data.azurerm_kusto_cluster.cluster.id
  table_name                   = var.kusto_table_name
  mapping_rule_name            = "${var.kusto_table_name}_mapping"
  depends_on                   = [azurerm_eventgrid_system_topic_event_subscription.example]
}