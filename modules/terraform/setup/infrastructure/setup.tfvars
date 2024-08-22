tags = {
  "project" = "Telescope"
  "owner"   = "AKS Team"
}
azure_config = {
  service_connection_name        = "Azure-for-Telescope"
  service_connection_description = "Managed by Terraform"
  subscription = {
    id     = "00000000-0000-0000-0000-000000000000"
    name   = "Azure Test Subscription"
    tenant = "00000000-0000-0000-0000-000000000000"
  }
  resource_group = {
    name     = "telescope20240819"
    location = "eastus"
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
      name     = "Standard_E16ads_v5"
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
  user_name                      = "telescope"
  service_connection_name        = "AWS-for-Telescope"
  service_connection_description = "Managed by Terraform"
}
azuredevops_config = {
  organization_name = "akstelescope"
  project_name      = "telescope"
  variable_groups   = []
}
