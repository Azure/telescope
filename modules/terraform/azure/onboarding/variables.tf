
variable "owner" {
  description = "owner of the test scenario"
  type        = string
  default     = "azure_devops"
}

variable "scenario_name" {
  description = "name of the test scenario"
  type        = string
  default     = null
}

variable "scenario_type" {
  description = "type of the test scenario"
  type        = string
  default     = null
}

variable "scenario_version" {
  description = "version of the test scenario"
  type        = string
  default     = null
}

variable "resource_group_name" {
  description = "resource group name"
  type        = string
  default     = null
}

variable "storage_account_name" {
  description = "storage account name"
  type        = string
  default     = null
}

variable "storage_container_name" {
  description = "storage container name"
  type        = string
  default     = null
}

variable "kusto_cluster_name" {
  description = "kusto cluster name"
  type        = string
  default     = null
}

variable "kusto_database_name" {
  description = "kusto database name"
  type        = string
  default     = null
}

variable "kusto_table_name" {
  description = "kusto table name"
  type        = string
  default     = null
}

variable "eventhub_namespace_name" {
  description = "eventhub namespace name"
  type        = string
  default     = null
}

variable "eventgrid_topic_name" {
  description = "eventgrid topic name"
  type        = string
  default     = null
}


variable "table_creation_script" {
  description = "table creation script"
  type        = string
  default     = null
}
