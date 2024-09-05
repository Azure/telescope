tags = {
  "project" = "Telescope"
  "owner"   = "AKS Team"
}
github_config = {
  service_connection_description = "Managed by Terraform"
  service_connection_name        = "Github-for-Telescope"
}
azure_config = {
  service_connection_name        = "Azure-for-Telescope"
  service_connection_description = "Managed by Terraform"
  subscription_id                = null
  resource_group = {
    location = "eastus"
  }
  storage_account = {
    account_tier              = "Standard"
    account_replication_type  = "LRS"
    shared_access_key_enabled = true
  }
  kusto_cluster = {
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
  user_name                      = "telescope20240819"
  policy_names                   = ["AdministratorAccess"]
  service_connection_name        = "AWS-for-Telescope"
  service_connection_description = "Managed by Terraform"
}
azuredevops_config = {
  organization_name = "akstelescope"
  project_name      = "telescope"
  variable_groups   = []
}
