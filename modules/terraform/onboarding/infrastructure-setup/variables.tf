variable "json_input" {
  description = "value of the json input for creating one time infrasturcture setup "
  type = object({
    owner                = string
    run_id               = string
    location             = string
    resource_group_name  = string
    storage_account_name = string
    kusto_cluster_name   = string
    kusto_database_names = list(string)
  })
  default = {
    owner                = "schinnapulla"
    run_id               = "08062024"
    location             = "eastus"
    resource_group_name  = "schinnapulla"
    storage_account_name = "schinnapulla"
    kusto_cluster_name   = "schinnapulla"
    kusto_database_names = ["perf-eval", "issue-repro"]
  }
}

variable "tags" {
  description = "Tags to be applied to all resources"
  type        = map(string)

}

variable "azure_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    resource_group = object({
      name     = string
      location = string
    })
    managed_identity = optional(object({
      name                 = string
      role_definition_name = string
    }))
    storage_account = object({
      name                      = string
      account_tier              = string
      account_replication_type  = string
      shared_access_key_enabled = bool
    })
    kusto_cluster = object({
      name = string
      sku = object({
        name     = string
        capacity = number
      })
      kusto_databases = list(object({
        name               = string
        hot_cache_period   = string
        soft_delete_period = string
      }))
    })
  })
}

variable "aws_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    region    = string
    user_name = string
  })
}

variable "azuredevops_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    project_name = string
    variable_groups = list(object({
      name         = string
      description  = string
      allow_access = optional(bool, false)
      variables = list(object({
        name  = string
        value = string
      }))
    }))
    service_connections = list(string)
  })

}
