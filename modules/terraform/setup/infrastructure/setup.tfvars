tags = {
  "project" = "Telescope"
  "owner"   = "AKS Team"
}
azure_config = {
  subscription = {
    id     = "00000000-0000-0000-0000-000000000000"
    name   = "Subscription Name"
    tenant = "00000000-0000-0000-0000-000000000000"
  }
  resource_group = {
    name     = "20240808"
    location = "eastus"
  }
  storage_account = {
    name                      = "telescope20240808"
    account_tier              = "Standard"
    account_replication_type  = "LRS"
    shared_access_key_enabled = true
  }
  kusto_cluster = {
    name = "telescope20240808"
    sku = {
      name     = "Standard_D13_v2"
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
# aws_config = {
# 	region = "us-east-1"
# 	user_name = "telescope"
# }
azuredevops_config = {
  organization_name = "akstelescope"
  project_name      = "telescope"
  # variable_groups = [
  #   {
  #     name         = "telescope"
  #     description  = "Variable group for telescope project"
  #     allow_access = false
  #     variables = [
  #       {
  #         name  = "CLIENT_ID"
  #         value = "12345678-1234-1234-1234-123456789012"
  #       },
  #       {
  #         name  = "SUBSCRIPTION_ID"
  #         value = "12345678-1234-1234-1234-123456789012"
  #       },
  #       {
  #         name  = "TENANT_ID"
  #         value = "12345678-1234-1234-1234-123456789012"
  #       }
  #     ]
  #   }
  # ]
  # service_connections = [
  #   "telescope-azure", "telescope-aws"
  # ]
}
