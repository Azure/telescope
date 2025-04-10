azure_devops_config = {
  project_name    = "telescope"
  variable_groups = []
  variables = [
    {
      name  = "AZURE_SUBSCRIPTION_ID"
      value = "9b8218f9-902a-4d20-a65c-e98acec5362f"
    },
    {
      name  = "AWS_SERVICE_CONNECTION"
      value = "AWS-for-Telescope"
    },
    {
      name  = "AZURE_SERVICE_CONNECTION"
      value = "Azure-for-Telescope"
  }, {
      name  = "run_id"
      value = "krunaljain-cilscale-26281-20250410133050"
    }, {
      name  = "LOCATION"
      value = "eastus2"
    },{
      name  = "role"
      value = "ces"
    }]
  pipeline_config = {
    name = "Cilium Framework E2E test"
    path = "\\"
    repository = {
      repo_type               = "GitHub"
      repository_name         = "Azure/telescope"
      branch_name             = "feature/test_framework"
      yml_path                = "pipelines/perf-eval/CNI Benchmark/cilium-test-framework.yml"
      service_connection_name = "Github-for-Telescope"
    }
    agent_pool_name = "AKS-Telescope-Ubuntu-EastUS2"
  }
  service_connections = ["AWS-for-Telescope", "Azure-for-Telescope"]
}