terraform {
  required_providers {
    azuredevops = {
      source  = "microsoft/azuredevops"
      version = ">=0.1.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 3.93.0"
    }
  }
}

provider "azuredevops" {
}

provider "azurerm" {
  features {}
}

data "azurerm_subscription" "subscription" {
}

locals {
  azure_storage_account_variable = {
    name  = "AZURE_STORAGE_ACCOUNT_NAME"
    value = var.storage_account_name
  }
  pipeline_variables = concat([for variable in var.azure_devops_config.variables : {
    name  = variable.name
    value = (variable.name == "AZURE_SUBSCRIPTION_ID" && variable.value == "00000000-0000-0000-0000-000000000000") ? data.azurerm_subscription.subscription.subscription_id : variable.value
  }], [local.azure_storage_account_variable])

}

data "azuredevops_project" "project" {
  name = var.azure_devops_config.project_name
}

data "azuredevops_variable_group" "variable_groups" {
  count      = length(var.azure_devops_config.variable_groups)
  project_id = data.azuredevops_project.project.id
  name       = var.azure_devops_config.variable_groups[count.index]
}

data "azuredevops_serviceendpoint_github" "service_connection" {
  count                 = var.azure_devops_config.pipeline_config.repository.service_connection_name != null ? 1 : 0
  project_id            = data.azuredevops_project.project.id
  service_endpoint_name = var.azure_devops_config.pipeline_config.repository.service_connection_name
}

data "azuredevops_git_repository" "repository" {
  count      = var.azure_devops_config.pipeline_config.repository.repo_type == "TfsGit" ? 1 : 0
  project_id = data.azuredevops_project.project.id
  name       = var.azure_devops_config.pipeline_config.repository.repository_name
}

resource "azuredevops_build_definition" "Pipeline" {
  project_id      = data.azuredevops_project.project.id
  name            = var.azure_devops_config.pipeline_config.name
  path            = var.azure_devops_config.pipeline_config.path
  agent_pool_name = var.azure_devops_config.pipeline_config.agent_pool_name


  repository {
    repo_type             = var.azure_devops_config.pipeline_config.repository.repo_type
    repo_id               = var.azure_devops_config.pipeline_config.repository.repo_type == "TfsGit" ? data.azuredevops_git_repository.repository[0].id : var.azure_devops_config.pipeline_config.repository.repository_name
    branch_name           = var.azure_devops_config.pipeline_config.repository.branch_name
    yml_path              = var.azure_devops_config.pipeline_config.repository.yml_path
    service_connection_id = var.azure_devops_config.pipeline_config.repository.repo_type == "GitHub" ? data.azuredevops_serviceendpoint_github.service_connection[0].id : null
  }

  variable_groups = length(data.azuredevops_variable_group.variable_groups) > 0 ? [for group in data.azuredevops_variable_group.variable_groups : group.id] : null

  dynamic "variable" {
    for_each = local.pipeline_variables
    content {
      name  = variable.value.name
      value = variable.value.value
    }
  }

}

data "azuredevops_agent_queue" "agent_queue" {
  project_id = data.azuredevops_project.project.id
  name       = var.azure_devops_config.pipeline_config.agent_pool_name
}

resource "azuredevops_pipeline_authorization" "approve" {
  project_id  = data.azuredevops_project.project.id
  resource_id = data.azuredevops_agent_queue.agent_queue.id
  type        = "queue"
  pipeline_id = azuredevops_build_definition.Pipeline.id
}

data "azuredevops_serviceendpoint_azurerm" "service_connection" {
  count                 = length(var.azure_devops_config.service_connections)
  project_id            = data.azuredevops_project.project.id
  service_endpoint_name = var.azure_devops_config.service_connections[count.index]
}

resource "azuredevops_pipeline_authorization" "service_connection_authorization" {
  count       = length(var.azure_devops_config.service_connections)
  project_id  = data.azuredevops_project.project.id
  resource_id = data.azuredevops_serviceendpoint_azurerm.service_connection[count.index].id
  type        = "endpoint"
  pipeline_id = azuredevops_build_definition.Pipeline.id
}
