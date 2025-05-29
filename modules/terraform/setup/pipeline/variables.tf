variable "azure_devops_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    project_name    = string
    variable_groups = optional(list(string), [])
    variables = list(object({
      name  = string
      value = string
    }))
    pipeline_config = object({
      name = string
      path = optional(string, "//")
      repository = object({
        repo_type               = string
        repository_name         = string
        branch_name             = optional(string, "main")
        yml_path                = string
        service_connection_name = optional(string, null)
      })
      agent_pool_name = string
    })
    service_connections = list(string)
  })

  validation {
    condition = alltrue([
      contains([for v in var.azure_devops_config.variables : v.name], "AZURE_SUBSCRIPTION_ID"),
      contains([for v in var.azure_devops_config.variables : v.name], "AZURE_SERVICE_CONNECTION")
    ])
    error_message = "The following variables are required: AZURE_SUBSCRIPTION_ID, AZURE_SERVICE_CONNECTION, AWS_SERVICE_CONNECTION"
  }

  validation {
    condition     = contains(["GitHub", "TfsGit"], var.azure_devops_config.pipeline_config.repository.repo_type)
    error_message = "Valid values for repo_type are GitHub and TfsGit"
  }

  validation {
    condition     = (var.azure_devops_config.pipeline_config.repository.repo_type == "GitHub" && var.azure_devops_config.pipeline_config.repository.service_connection_name != null) || (var.azure_devops_config.pipeline_config.repository.repo_type == "TfsGit" && var.azure_devops_config.pipeline_config.repository.service_connection_name == null)
    error_message = "service_connection_name is required when repo_type is GitHub and should be null when repo_type is TfsGit"
  }

  validation {
    condition     = (var.azure_devops_config.pipeline_config.repository.repo_type == "GitHub" && strcontains(var.azure_devops_config.pipeline_config.repository.repository_name, "/")) || (var.azure_devops_config.pipeline_config.repository.repo_type == "TfsGit" && !strcontains(var.azure_devops_config.pipeline_config.repository.repository_name, "/"))
    error_message = "Repository Name for a GitHub repository should be in the form: OwnerName/Repository and for TfsGit should not contain a /"
  }
}

variable "storage_account_name" {
  description = "Name of the storage account"
  type        = string
}
