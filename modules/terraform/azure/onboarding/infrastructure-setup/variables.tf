variable "json_input" {
  description = "value of the json input for creating one time infrasturcture setup "
  type = object({
    owner                = string
    run_id               = string
    location             = string
    resource_group_name  = string
    storage_account_name = string
    kusto_cluster_name   = string
    kusto_database_name  = string
  })
}
