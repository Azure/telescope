provider "azurerm" {
  features {}
  storage_use_azuread = true
}

locals {
  tags = {
    owner  = var.json_input.owner
    run_id = var.json_input.run_id
  }

  _scenario_type       = replace(trimspace(var.json_input.scenario_type), "/[./-]/", "_")
  _scenario_name       = replace(trimspace(var.json_input.scenario_name), "/[./-]/", "_")
  _scenario_version    = replace(trimspace(var.json_input.scenario_version), "/[./-]/", "_")
  kusto_table_name     = "${local._scenario_name}_${local._scenario_version}"
  kusto_database_name  = local._scenario_type
  data_connection_name = substr("${trimspace(var.json_input.scenario_name)}-${trimspace(var.json_input.scenario_version)}", 0, 40)
}

# Resource Group
data "azurerm_resource_group" "rg" {
  name = "telescope"
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

# Azure Data Explorer Cluster
data "azurerm_kusto_cluster" "cluster" {
  name                = var.json_input.kusto_cluster_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# Bash Script
resource "local_file" "bash_script" {
  filename = "${path.module}/script.sh"
  content  = <<-EOT
							#!/bin/bash
							set -e
							eval "$(jq -r '@sh "RESOURCE_GROUP_NAME=\(.RESOURCE_GROUP_NAME) KUSTO_TABLE_NAME=\(.KUSTO_TABLE_NAME)"')"
							eventhub_namespaces=$(az eventhubs namespace list --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)
							create_eventhub_namespace=false
							for eventhub_namespace in $eventhub_namespaces; do
								eventhub_instances=$(az eventhubs eventhub list --namespace-name $eventhub_namespace --resource-group $RESOURCE_GROUP_NAME --query '[].{Name:name}' --output tsv)

								if [ $(echo $eventhub_instances | wc -w) -eq 10 ]; then
									create_eventhub_namespace=true
									eventhub_namespace=null
								else
									create_eventhub_namespace=false															
									break
								fi
							done
							result_file="./result.json"
							table_script_path="../../../python/kusto"
							table_creation_script=$(python3 $table_script_path/generate_commands.py "$KUSTO_TABLE_NAME" "$result_file")
							jq -n --arg create_eventhub_namespace "$create_eventhub_namespace" --arg eventhub_namespace "$eventhub_namespace" --arg table_script "$table_creation_script" '{"create_eventhub_namespace":$create_eventhub_namespace,"eventhub_namespace":$eventhub_namespace, "table_creation_script":$table_script}'
						EOT	
}

data "external" "bash_script" {
  program = ["bash", "${local_file.bash_script.filename}"]
  query = {
    RESOURCE_GROUP_NAME = data.azurerm_resource_group.rg.name
    KUSTO_TABLE_NAME    = local.kusto_table_name
  }
}

output "namespace" {
  value = data.external.bash_script.result
}

# # Azure Data Explorer Database
data "azurerm_kusto_database" "database" {
  name                = local.kusto_database_name
  resource_group_name = data.azurerm_resource_group.rg.name
  cluster_name        = data.azurerm_kusto_cluster.cluster.name
}

resource "azurerm_kusto_script" "script" {
  name                               = "kusto-script-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  database_id                        = data.azurerm_kusto_database.database.id
  continue_on_errors_enabled         = false
  force_an_update_when_value_changed = "first"
  script_content                     = base64decode(data.external.bash_script.result["table_creation_script"])
}

data "azurerm_eventhub_namespace" "eventhub_ns" {
  count               = tobool(data.external.bash_script.result["create_eventhub_namespace"]) ? 0 : 1
  name                = data.external.bash_script.result["eventhub_namespace"]
  resource_group_name = data.azurerm_resource_group.rg.name
  depends_on          = [data.external.bash_script]
}

resource "azurerm_eventhub_namespace" "eventhub_ns" {
  count               = tobool(data.external.bash_script.result["create_eventhub_namespace"]) ? 1 : 0
  name                = "ADX-EG-telescope-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  sku                 = "Standard"
  capacity            = 1
  tags                = local.tags
  depends_on          = [data.external.bash_script]
}

resource "azurerm_eventhub" "eventhub" {
  name                = "adx-eg-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  namespace_name      = data.external.bash_script.result["create_eventhub_namespace"] ? azurerm_eventhub_namespace.eventhub_ns[0].name : data.azurerm_eventhub_namespace.eventhub_ns[0].name
  resource_group_name = data.azurerm_resource_group.rg.name
  partition_count     = 8
  message_retention   = 7
  depends_on          = [data.external.bash_script]
}

resource "azurerm_role_assignment" "eventhub_role_assignment" {
  scope                = azurerm_eventhub.eventhub.id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = data.azurerm_kusto_cluster.cluster.identity[0].principal_id
}

resource "azurerm_eventhub_consumer_group" "consumer_group" {
  name                = "default"
  namespace_name      = tobool(data.external.bash_script.result["create_eventhub_namespace"]) ? azurerm_eventhub_namespace.eventhub_ns[0].name : data.azurerm_eventhub_namespace.eventhub_ns[0].name
  eventhub_name       = azurerm_eventhub.eventhub.name
  resource_group_name = data.azurerm_resource_group.rg.name
  depends_on          = [data.external.bash_script]
}

resource "azurerm_eventgrid_event_subscription" "event_subscription" {
  name                  = "ADX-EG-${formatdate("MM-DD-YYYY-hh-mm-ss", timestamp())}"
  scope                 = data.azurerm_storage_account.storage.id
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
  name                         = local.data_connection_name
  resource_group_name          = data.azurerm_resource_group.rg.name
  location                     = data.azurerm_resource_group.rg.location
  cluster_name                 = data.azurerm_kusto_cluster.cluster.name
  database_name                = data.azurerm_kusto_database.database.name
  storage_account_id           = data.azurerm_storage_account.storage.id
  blob_storage_event_type      = "Microsoft.Storage.BlobCreated"
  eventgrid_resource_id        = azurerm_eventgrid_event_subscription.event_subscription.id
  eventhub_id                  = azurerm_eventhub.eventhub.id
  eventhub_consumer_group_name = azurerm_eventhub_consumer_group.consumer_group.name
  managed_identity_resource_id = data.azurerm_kusto_cluster.cluster.id
  database_routing_type        = "Single"
  table_name                   = local.kusto_table_name
  data_format                  = "JSON"
  mapping_rule_name            = "${local.kusto_table_name}_mapping"
  depends_on                   = [azurerm_eventgrid_event_subscription.event_subscription, azurerm_kusto_script.script, azurerm_eventhub_consumer_group.consumer_group]
}
