variable "json_input" {
  description = "value of the table input for creating the table & data ingestion setup"
  type = object({
    owner                = string
    run_id               = string
    scenario_name        = string
    scenario_type        = string
    scenario_version     = string
    resource_group_name  = string
    storage_account_name = string
    kusto_cluster_name   = string
    # table_creation_script = string
  })
}
