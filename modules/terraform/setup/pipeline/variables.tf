variable "azure_devops_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    project_name            = string
    variable_groups_to_link = optional(list(string), [])
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
    condition     = contains(["GitHub", "TfsGit"], var.azure_devops_config.pipeline_config.repository.repo_type)
    error_message = "Valid values for repo_type are GitHub and TfsGit"
  }

  validation {
    condition     = var.azure_devops_config.pipeline_config.repository.repo_type == "GitHub" && var.azure_devops_config.pipeline_config.repository.service_connection_name != null
    error_message = "service_connection_name is required when repo_type is GitHub"
  }
}
