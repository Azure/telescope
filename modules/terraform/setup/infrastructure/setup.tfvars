tags = {
  "project" = "Telescope"
  "owner"   = "AKS Team"
}
azure_config = {
  service_connection_name        = "Azure-for-Telescope"
  service_connection_description = "Managed by Terraform"
  subscription = {
    id     = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
    name   = "Cloud Compete Testing"
    tenant = "72f988bf-86f1-41af-91ab-2d7cd011db47"
  }
  resource_group = {
    name     = "schinnapulla20240819"
    location = "eastus2"
  }
  storage_account = {
    name                      = "telescope20240819"
    account_tier              = "Standard"
    account_replication_type  = "LRS"
    shared_access_key_enabled = true
  }
  kusto_cluster = {
    name     = "telescope20240819"
    location = "eastus"
    sku = {
      name     = "Standard_L16s_v3"
      capacity = 2
    }
    kusto_databases = [
      {
        name               = "perf_eval"
        hot_cache_period   = "P31D"
        soft_delete_period = "P365D"
      }
    ]
  }
}
aws_config = {
  region                         = "us-east-1"
  user_name                      = "azuretelescope"
  service_connection_name        = "AWS-Service-Connection"
  service_connection_description = "Managed by Terraform"
}
azuredevops_config = {
  organization_name = "azuretelescope"
  project_name      = "telescope"
  variable_groups   = []
}
