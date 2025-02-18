variable "owner" {
  description = "Owner of the resource"
  type        = string
}

variable "scenario_name" {
  description = "Name of the scenario"
  type        = string
}

variable "scenario_type" {
  description = "Type of the scenario"
  type        = string
}

variable "scenario_version" {
  description = "Version of the scenario"
  type        = string
  default     = "main"
}

variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "storage_account_name" {
  description = "Name of the Azure storage account"
  type        = string
}

variable "kusto_cluster_name" {
  description = "Name of the Azure Kusto cluster"
  type        = string
}

variable "create_eventhub_namespace" {
  description = "Flag to create an Event Hub namespace"
  type        = bool
}

variable "eventhub_namespace" {
  description = "Name of the Event Hub namespace"
  type        = string
}
