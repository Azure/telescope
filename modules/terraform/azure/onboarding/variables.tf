
variable "onboarding_input" {
  description = "values for onboarding new test scenario"
  type = object({
    owner                       = string
    resource_group_name         = string
    storage_account_name        = string
    storage_container_name      = string
    kusto_cluster_name          = string
    kusto_database_name         = string
    kusto_table_name            = string
    eventhub_namespace_name     = string
    eventhub_name               = string
    eventgrid_topic_name        = string
    eventgrid_subscription_name = string
    data_connection_name        = string
    table_creation_script_path  = string
  })
  default = {
    owner                       = "azure_devops"
    resource_group_name         = "sumanth-onboarding-automation"
    storage_account_name        = "sumanthtelescope"
    storage_container_name      = "sumanthtest"
    kusto_cluster_name          = "sumanthtelescope"
    kusto_database_name         = "sumanthtestdb"
    kusto_table_name            = "sumanthtable"
    eventhub_namespace_name     = "sumanthtelescope"
    eventhub_name               = "sumanthtesteventhub"
    eventgrid_topic_name        = "sumanthtelescope"
    eventgrid_subscription_name = "sumanthtestsubscription"
    data_connection_name        = "sumanthtestconnection"
  }
}