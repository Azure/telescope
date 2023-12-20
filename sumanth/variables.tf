variable "resource_group_name" {
  description = "Name of the scenario"
  type        = string
  default     = "sumanth-onboarding-automation"
}

variable "storage_account_name" {
  description = "Name of the storage account"
  type        = string
  default     = "sumanthtelescope"
}

variable "storage_container_name" {
  description = "Name of the storage container"
  type        = string
  default     = "sumanthtest"
}

variable "kusto_cluster_name" {
  description = "Name of the kusto cluster"
  type        = string
  default     = "sumanthtelescope"
}

variable "kusto_database_name" {
  description = "Name of the kusto database"
  type        = string
  default     = "sumanthtestdb"
}

variable "kusto_table_name" {
  description = "Name of the kusto table"
  type        = string
  default     = "sumanthtable"
}

variable "eventhub_namespace_name" {
  description = "Name of the eventhub namespace"
  type        = string
  default     = "sumanthtelescope"
}

variable "eventhub_name" {
  description = "Name of the eventhub"
  type        = string
  default     = "sumanthtesteventhub"
}

variable "eventgrid_topic_name" {
  description = "Name of the eventgrid topic"
  type        = string
  default     = "sumanthtelescope"
}

variable "eventgrid_subscription_name" {
  description = "Name of the eventgrid subscription"
  type        = string
  default     = "sumanthtestsubscription"
}

variable "data_connection_name" {
  description = "Name of the data connection"
  type        = string
  default     = "sumanthtestconnection"
}