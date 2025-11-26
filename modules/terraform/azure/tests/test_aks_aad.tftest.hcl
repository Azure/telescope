mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000000"
      object_id = "12345678-1234-5678-9abc-def012345678"
    }
  }
}

variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus",
    "public_key_path" : "public_key_path",
    "aks_aad_enabled" : true
  }

  aks_config_list = [
    {
      role        = "test"
      aks_name    = "test"
      dns_prefix  = "test"
      subnet_name = "test-subnet-1"
      sku_tier    = "Standard"
      network_profile = {
        network_plugin      = "azure"
        network_plugin_mode = "overlay"
        network_policy      = "azure"
        network_dataplane   = "azure"
      }
      default_node_pool = {
        name                         = "default"
        node_count                   = 1
        vm_size                      = "Standard_D32s_v3"
        os_disk_type                 = "Managed"
        only_critical_addons_enabled = false
        temporary_name_for_rotation  = "defaulttmp"
      }
      extra_node_pool = []
    }
  ]
}

# Test case 1: Verify AAD is enabled with default service principal object_id
run "valid_aad_enabled" {

  command = plan

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) > 0
    error_message = "Expected: AAD block to exist when enabled"
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids) == 1
    error_message = "Expected: 1 admin group (default object_id) \n Actual: ${length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids)}"
  }

  assert {
    condition = contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "12345678-1234-5678-9abc-def012345678"
    )
    error_message = "Expected: default object_id from service principal to be used as admin group"
  }

  assert {
    condition     = module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].azure_rbac_enabled == true
    error_message = "Expected: azure_rbac_enabled defaults to true"
  }

  assert {
    condition     = module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].tenant_id == "00000000-0000-0000-0000-000000000000"
    error_message = "Expected: tenant_id should use value from data source"
  }
}

# Test case 2: Verify AAD is disabled when aks_aad_enabled is not set
run "valid_aad_disabled" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 0
    error_message = "Expected: AAD block should not exist when not enabled"
  }
}

# Test case 3: Verify AAD is disabled when aks_aad_enabled is false
run "valid_aad_explicitly_disabled" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : false
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 0
    error_message = "Expected: AAD block should not exist when explicitly disabled"
  }
}
