variable "json_input" {
  description = "value of the json input for onboarding automation"
  type = object({
    owner                     = string
    run_id                    = string
    formatted_resource_name   = string
    scenario_name             = string
    scenario_type             = string
    scenario_version          = string
    resource_group_name       = string
    storage_account_name      = string
    kusto_cluster_name        = string
    kusto_database_name       = string
    kusto_table_name          = string
    create_eventhub_namespace = bool
    eventhub_namespace_name   = optional(string)
    eventhub_instance_name    = optional(string)
    create_eventhub_instance  = bool
    eventgrid_topic_name      = string
    table_creation_script     = string
  })
}
