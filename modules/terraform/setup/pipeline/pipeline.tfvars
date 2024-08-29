azure_devops_config = {
  project_name    = "telescope"
  variable_groups = []
  variables = [
    {
      name  = "AZURE_STORAGE_ACCOUNT_NAME"
      value = "telescope"
    },
    {
      name  = "AZURE_STORAGE_SUBSCRIPTION"
      value = "00000000-0000-0000-0000-000000000000"
    },
    {
      name  = "AZURE_SUBSCRIPTION_ID"
      value = "00000000-0000-0000-0000-000000000000"
    },
    {
      name  = "AWS_SERVICE_CONNECTION"
      value = "AWS-for-Telescope"
    },
    {
      name  = "AZURE_SERVICE_CONNECTION"
      value = "Azure-for-Telescope"
  }]
  pipeline_config = {
    name = "Test Pipeline"
    path = "\\"
    repository = {
      repo_type               = "GitHub"
      repository_name         = "Azure/telescope"
      branch_name             = "main"
      yml_path                = "test-pipeline.yml"
      service_connection_name = null
    }
    agent_pool_name = "Azure Pipelines"
  }
  service_connections = ["AWS-for-Telescope", "Azure-for-Telescope"]
}