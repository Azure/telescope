variable "azure_devops_config" {
  description = "All the resources that are required for the infrastructure setup"
  type = object({
    project_name            = string
    variable_groups_to_link = list(string)
    pipeline_config = object({
      name = string
      path = optional(string, "//")
      repository = object({
        repo_type               = string
        repository_name         = string
        branch_name             = string
        yml_path                = string
        service_connection_name = optional(string, null)
      })
      agent_pool_name = string
    })
  })
}
