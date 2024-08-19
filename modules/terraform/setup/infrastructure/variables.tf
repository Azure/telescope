variable "tags" {
  description = "Tags to be applied to all resources"
  type        = map(string)

}

variable "azure_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    service_connection_name        = string
    service_connection_description = string
    subscription = object({
      id     = string
      name   = string
      tenant = string
    })
    resource_group = object({
      name     = string
      location = string
    })
    storage_account = object({
      name                      = string
      account_tier              = string
      account_replication_type  = string
      shared_access_key_enabled = bool
    })
    kusto_cluster = object({
      name     = string
      location = optional(string, null)
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
    region                         = string
    user_name                      = string
    service_connection_name        = string
    service_connection_description = string
  })
}

variable "azuredevops_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    organization_name = string
    project_name      = string
    variable_groups = optional(list(object({
      name         = string
      description  = string
      allow_access = optional(bool, false)
      variables = list(object({
        name  = string
        value = string
      }))
    })))
  })
}
