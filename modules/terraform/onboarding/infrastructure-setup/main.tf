terraform {
  required_version = ">=1.5.6"
  required_providers {
    azuredevops = {
      source  = "microsoft/azuredevops"
      version = ">=0.1.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "<= 5.38"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 3.93.0"
    }
  }
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
}

provider "aws" {
  region = var.aws_config.region
}

provider "azuredevops" {
}

# Locals for tags
locals {
  tags = var.tags
  database_config_map = {
    for db in var.azure_config.kusto_databases : dd.name => db
  }
}

# Azure Resource Group
resource "azurerm_resource_group" "rg" {
  name     = var.azure_config.resource_group.name
  location = var.azure_config.resource_group.location
  tags     = local.tags
}

# Managed Identity
resource "azurerm_user_assigned_identity" "mi" {
  count               = var.azure_config.managed_identity != null ? 1 : 0
  name                = var.azure_config.managed_identity.name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

# Role Assignment
resource "azurerm_role_assignment" "owner_role_assignment" {
  count                = var.azure_config.managed_identity != null ? 1 : 0
  role_definition_name = var.azure_config.managed_identity.role_definition_name
  scope                = azurerm_resource_group.rg.id
  principal_id         = azurerm_user_assigned_identity.mi.principal_id
}

# Storage Account
resource "azurerm_storage_account" "storage" {
  name                      = var.azure_config.storage_account.name
  resource_group_name       = azurerm_resource_group.rg.name
  location                  = azurerm_resource_group.rg.location
  account_tier              = var.azure_config.storage_account.account_tier
  account_replication_type  = var.azure_config.storage_account.account_replication_type
  shared_access_key_enabled = var.azure_config.storage_account.shared_access_key_enabled
  tags                      = local.tags
}

# Role Assignment
resource "azurerm_role_assignment" "blob_contributor_role_assignment" {
  role_definition_name = "Storage Blob Data Contributor"
  scope                = azurerm_storage_account.storage.id
  principal_id         = azurerm_user_assigned_identity.mi.principal_id
}

# Storage Container
resource "azurerm_storage_container" "container" {
  for_each             = local.database_config_map
  name                 = each.key
  storage_account_name = azurerm_storage_account.storage.name
}


# Kusto Cluster
resource "azurerm_kusto_cluster" "cluster" {
  name                = var.azure_config.kusto_cluster.name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku {
    name     = var.azure_config.kusto_cluster.sku.name
    capacity = var.azure_config.kusto_cluster.sku.capacity
  }
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# Role Assignment
resource "azurerm_role_assignment" "storage_role_assignment" {
  scope                = azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_kusto_cluster.cluster.identity[0].principal_id
}

# Kusto Database
resource "azurerm_kusto_database" "database" {
  for_each            = local.database_config_map
  name                = each.key
  resource_group_name = azurerm_resource_group.rg.name
  cluster_name        = azurerm_kusto_cluster.cluster.name
  location            = azurerm_resource_group.rg.location
  hot_cache_period    = each.value.hot_cache_period
  soft_delete_period  = each.value.soft_delete_period
}

# Lock Azure Resource Group
resource "azurerm_management_lock" "resource-group-level" {
  name       = "LockResourceGroup"
  scope      = azurerm_resource_group.rg.id
  lock_level = "Delete"
  notes      = "This Resource Group is not allowed to be deleted"
}

# AWS IAM User

resource "aws_iam_user" "user" {
  name = var.aws_config.user_name
  path = "/"
}

# AWS IAM Access Key
resource "aws_iam_access_key" "access_key" {
  user = aws_iam_user.user.name
}

locals {
  credentials_variables = [{
    name        = "AWS Credentials"
    description = "This variable group contains all the AWS secrets required for the infrastructure"
    variables = [
      {
        name  = "AWS_ACCESS_KEY_ID"
        value = aws_iam_access_key.access_key.id
      },
      {
        name  = "AWS_SECRET_ACCESS_KEY"
        value = aws_iam_access_key.access_key.secret
      }
    ]
  }]
}

# Azure DevOps 
data "azuredevops_project" "project" {
  name = var.azuredevops_config.project_name
}

# Azure DevOps Non-Secret Variable Groups
resource "azuredevops_variable_group" "variable_groups" {
  for_each     = { for group in var.azuredevops_config.variable_groups : group.name => group }
  project_id   = data.azuredevops_project.project.id
  name         = each.value.name
  description  = each.value.description
  allow_access = each.value.allow_access

  dynamic "variable" {
    for_each = each.value.variables
    content {
      name  = variable.value.name
      value = variable.value.value
    }
  }
}

# Azure DevOps Secret Variable Groups
resource "azuredevops_variable_group" "secret_variable_groups" {
  for_each   = { for group in local.credentials_variables : group.name => group }
  project_id = data.azuredevops_project.project.id

  name         = each.value.name
  description  = each.value.description
  allow_access = false
  dynamic "variable" {
    for_each = each.value.variables
    content {
      name         = variable.value.name
      secret_value = variable.value.value
    }
  }
}
