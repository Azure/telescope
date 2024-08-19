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
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.15.0"
    }
  }
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
  subscription_id     = var.azure_config.subscription.id
}

provider "aws" {
  region = var.aws_config.region
}

provider "azuredevops" {
}

provider "azuread" {
  tenant_id = var.azure_config.subscription.tenant
}

## Step 1: Set up service connection to Azure

data "azuredevops_project" "ado_project" {
  name = var.azuredevops_config.project_name
}

resource "azuredevops_serviceendpoint_azurerm" "azure_service_connection" {
  project_id                             = data.azuredevops_project.ado_project.id
  service_endpoint_name                  = var.azure_config.service_connection_name
  description                            = var.azure_config.service_connection_description
  service_endpoint_authentication_scheme = "WorkloadIdentityFederation"
  azurerm_spn_tenantid                   = var.azure_config.subscription.tenant
  azurerm_subscription_id                = var.azure_config.subscription.id
  azurerm_subscription_name              = var.azure_config.subscription.name
}

## Step 2: Set up resource group and grant service principal permission in Azure

# Locals for tags
locals {
  tags = var.tags
  database_config_map = {
    for db in var.azure_config.kusto_cluster.kusto_databases : db.name => db
  }
}

# Service Principal
data "azuread_service_principal" "service_principal" {
  application_id = azuredevops_serviceendpoint_azurerm.azure_service_connection.service_principal_id
}

# Subscription
data "azurerm_subscription" "subscription" {
  subscription_id = var.azure_config.subscription.id
}

# Role Assignment
resource "azurerm_role_assignment" "subscription_owner_role_assignment" {
  role_definition_name = "owner"
  scope                = data.azurerm_subscription.subscription.id
  principal_id         = data.azuread_service_principal.service_principal.object_id
}

# Azure Resource Group
resource "azurerm_resource_group" "rg" {
  name     = var.azure_config.resource_group.name
  location = var.azure_config.resource_group.location
  tags     = local.tags
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

# Storage Role Assignment
resource "azurerm_role_assignment" "storage_blob_contributor_role_assignment" {
  role_definition_name = "Storage Blob Data Contributor"
  scope                = azurerm_storage_account.storage.id
  principal_id         = data.azuread_service_principal.service_principal.object_id
}

# Storage Container
resource "azurerm_storage_container" "container" {
  for_each             = local.database_config_map
  name                 = replace(each.key, "_", "-")
  storage_account_name = azurerm_storage_account.storage.name
}


# Kusto Cluster
resource "azurerm_kusto_cluster" "cluster" {
  name                = var.azure_config.kusto_cluster.name
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.azure_config.kusto_cluster.location != null ? var.azure_config.kusto_cluster.location : azurerm_resource_group.rg.location
  sku {
    name     = var.azure_config.kusto_cluster.sku.name
    capacity = var.azure_config.kusto_cluster.sku.capacity
  }
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# Kusto Role Assignment
resource "azurerm_kusto_cluster_principal_assignment" "kusto_role_assignment" {
  name                = data.azuread_service_principal.service_principal.display_name
  resource_group_name = azurerm_resource_group.rg.name
  cluster_name        = azurerm_kusto_cluster.cluster.name

  tenant_id      = data.azuread_service_principal.service_principal.application_tenant_id
  principal_id   = data.azuread_service_principal.service_principal.object_id
  principal_type = "App"
  role           = "AllDatabasesAdmin"
}

# Kusto Database
resource "azurerm_kusto_database" "database" {
  for_each            = local.database_config_map
  name                = each.key
  resource_group_name = azurerm_resource_group.rg.name
  cluster_name        = azurerm_kusto_cluster.cluster.name
  location            = var.azure_config.kusto_cluster.location != null ? var.azure_config.kusto_cluster.location : azurerm_resource_group.rg.location
  hot_cache_period    = each.value.hot_cache_period
  soft_delete_period  = each.value.soft_delete_period
}

# Lock Azure Resource Group
resource "azurerm_management_lock" "resource-group-level" {
  name       = "LockResourceGroup"
  scope      = azurerm_resource_group.rg.id
  lock_level = "CanNotDelete"
  notes      = "This Resource Group is not allowed to be deleted"
}

## Step 3: Set up AWS IAM User and Access Key

# AWS IAM User
resource "aws_iam_user" "user" {
  name = var.aws_config.user_name
  path = "/"
}

# AWS IAM Access Key
resource "aws_iam_access_key" "access_key" {
  user = aws_iam_user.user.name
}

## Step 4: Set up service connection to AWS

resource "azuredevops_serviceendpoint_aws" "aws_service_connection" {
  project_id            = data.azuredevops_project.ado_project.id
  service_endpoint_name = var.aws_config.service_connection_name
  description           = var.aws_config.service_connection_description
  secret_access_key     = aws_iam_access_key.access_key.id
  access_key_id         = aws_iam_access_key.access_key.secret
}

# Azure DevOps Non-Secret Variable Groups
resource "azuredevops_variable_group" "variable_groups" {
  for_each     = { for group in var.azuredevops_config.variable_groups : group.name => group }
  project_id   = data.azuredevops_project.ado_project.id
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
