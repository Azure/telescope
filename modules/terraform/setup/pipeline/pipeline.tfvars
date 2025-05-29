azure_devops_config = {
  project_name    = "telescope"
  variable_groups = []
  variables = [
    {
      name  = "AZURE_SUBSCRIPTION_ID"
      value = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
    },
    {
      name  = "AZURE_SERVICE_CONNECTION"
      value = "Azure-for-Telescope-internal"
    },
    {
      name  = "AZURE_TELESCOPE_STORAGE_ACCOUNT_NAME"
      value = "telescopedata"
    },
    {
      name  = "SKIP_RESOURCE_MANAGEMENT"
      value = "false"
    }
  ]
  pipeline_config = {
    name = "Deployment Safeguards Perf test"
    path = "\\"
    repository = {
      repo_type               = "GitHub"
      repository_name         = "Azure/telescope"
      branch_name             = "nikelle/safeguards-perf-test"
      yml_path                = "pipelines/Safeguards Benchmark/safeguards-benchmark.yml"
      service_connection_name = "telescope (1)"
    }
    agent_pool_name = "AKS-Telescope-Ubuntu-EastUS2"
  }
  service_connections = ["Azure-for-Telescope-internal"]
}
