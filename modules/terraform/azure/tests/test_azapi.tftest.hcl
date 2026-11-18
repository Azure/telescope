mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000000"
      subscription_id = "12345678-1234-1234-1234-123456789012"
      object_id       = "12345678-1234-5678-9abc-def012345678"
    }
  }
}

mock_provider "azapi" {}

# Test case 1: Verify AzAPI resource body includes controlPlaneScalingProfile when specified
run "azapi_with_control_plane_scaling" {
  command = plan

  variables {
    owner               = "test"
    scenario_type       = "perf-eval"
    scenario_name       = "test-azapi"
    network_config_list = []
    aks_config_list     = []
    aks_cli_config_list = []
    azapi_config_list = [
      {
        role               = "client"
        aks_name           = "test-azapi-h2"
        dns_prefix         = "test-azapi-h2"
        kubernetes_version = "1.33.0"
        default_node_pool = {
          name    = "systempool1"
          count   = 3
          vm_size = "Standard_D2s_v5"
        }
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
        control_plane_scaling_profile = {
          scaling_size = "H2"
        }
      }
    ]
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "eastus2euap"
      run_id = "test123"
    }
    deletion_delay = "2h"
  }

  assert {
    condition     = module.azapi["test-azapi-h2"].resource_name == "test-azapi-h2"
    error_message = "AzAPI resource should be planned"
  }

  assert {
    condition     = module.azapi["test-azapi-h2"].resource_body.properties.controlPlaneScalingProfile.scalingSize == "H2"
    error_message = "controlPlaneScalingProfile.scalingSize should be 'H2'"
  }

  assert {
    condition = (
      module.azapi["test-azapi-h2"].resource_body.properties.enableRBAC &&
      module.azapi["test-azapi-h2"].resource_body.properties.aadProfile.managed &&
      module.azapi["test-azapi-h2"].resource_body.properties.aadProfile.enableAzureRBAC &&
      module.azapi["test-azapi-h2"].resource_body.properties.aadProfile.tenantID == "00000000-0000-0000-0000-000000000000" &&
      module.azapi["test-azapi-h2"].resource_body.properties.disableLocalAccounts &&
      !contains(keys(module.azapi["test-azapi-h2"].resource_body.properties.aadProfile), "adminGroupObjectIDs")
    )
    error_message = "AzAPI must default to managed Entra ID and Azure RBAC with local accounts disabled."
  }
}

# Test case 2: Verify AzAPI resource works without controlPlaneScalingProfile
run "azapi_without_control_plane_scaling" {
  command = plan

  variables {
    owner               = "test"
    scenario_type       = "perf-eval"
    scenario_name       = "test-azapi"
    network_config_list = []
    aks_config_list     = []
    aks_cli_config_list = []
    azapi_config_list = [
      {
        role               = "client"
        aks_name           = "test-azapi-std"
        dns_prefix         = "test-azapi-std"
        aad_enabled        = false
        kubernetes_version = "1.33.0"
        default_node_pool = {
          name    = "systempool1"
          count   = 3
          vm_size = "Standard_D2s_v5"
        }
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
      }
    ]
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "eastus"
      run_id = "test123"
    }
    deletion_delay = "2h"
  }

  assert {
    condition     = module.azapi["test-azapi-std"].resource_name == "test-azapi-std"
    error_message = "AzAPI resource should be planned without controlPlaneScalingProfile"
  }

  assert {
    condition     = !contains(keys(module.azapi["test-azapi-std"].resource_body.properties), "controlPlaneScalingProfile")
    error_message = "controlPlaneScalingProfile should not be present when not specified"
  }

  assert {
    condition = (
      !contains(keys(module.azapi["test-azapi-std"].resource_body.properties), "aadProfile") &&
      !contains(keys(module.azapi["test-azapi-std"].resource_body.properties), "enableRBAC") &&
      !module.azapi["test-azapi-std"].resource_body.properties.disableLocalAccounts
    )
    error_message = "Explicit AAD false must retain non-AAD and local-account behavior."
  }
}

# Test case 3: Verify empty azapi_config_list produces no resources
run "azapi_empty_config" {
  command = plan

  variables {
    owner                           = "test"
    scenario_type                   = "perf-eval"
    scenario_name                   = "test-azapi"
    network_config_list             = []
    aks_config_list                 = []
    aks_cli_config_list             = []
    azapi_config_list               = []
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "eastus"
      run_id = "test123"
    }
    deletion_delay = "2h"
  }

  assert {
    condition     = length(local.azapi_config_map) == 0
    error_message = "azapi_config_map should be empty when no azapi configs are provided"
  }
}

run "azapi_does_not_grant_metrics_implicitly" {
  command = plan

  module {
    source = "./azapi"
  }

  variables {
    resource_group_name = "test-rg"
    location            = "eastus"
    azapi_config = {
      role              = "client"
      aks_name          = "test-aks"
      dns_prefix        = "test-aks"
      default_node_pool = {}
    }
  }

  assert {
    condition     = length(azurerm_role_assignment.metrics_reader) == 0
    error_message = "Entra integration must not implicitly enable a metrics role assignment."
  }
}

run "azapi_metrics_reader_remains_explicit_opt_in" {
  command = plan

  module {
    source = "./azapi"
  }

  variables {
    resource_group_name = "test-rg"
    location            = "eastus"
    azapi_config = {
      role                   = "client"
      aks_name               = "test-aks"
      dns_prefix             = "test-aks"
      default_node_pool      = {}
      aad_enabled            = null
      metrics_reader_enabled = true
    }
  }

  assert {
    condition = (
      length(azurerm_role_assignment.metrics_reader) == 1 &&
      data.azurerm_role_definition.metrics_reader[0].name == "Telescope AKS Metrics Reader" &&
      azurerm_role_assignment.metrics_reader[0].principal_id == "12345678-1234-5678-9abc-def012345678"
    )
    error_message = "The existing metrics-reader opt-in must retain only its dedicated role assignment."
  }

  assert {
    condition     = output.resource_body.properties.aadProfile.enableAzureRBAC && output.resource_body.properties.disableLocalAccounts
    error_message = "Explicit null must use the enabled AAD default for direct AzAPI callers."
  }
}
