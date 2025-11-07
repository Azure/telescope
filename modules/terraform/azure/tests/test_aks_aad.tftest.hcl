mock_provider "azurerm" {
  source = "./tests"
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
    "aks_aad_enabled" : "true",
    "aks_aad_admin_group_object_ids" : "00000000-0000-0000-0000-000000000001,00000000-0000-0000-0000-000000000002"
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

# Test case 1: Verify AAD is enabled when aks_aad_enabled is "true"
run "valid_aad_enabled" {

  command = plan

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) > 0
    error_message = "Expected: AAD block to exist when enabled"
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids) == 2
    error_message = "Expected: 2 admin groups \n Actual: ${length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids)}"
  }

  assert {
    condition = contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "00000000-0000-0000-0000-000000000001"
    )
    error_message = "Expected: admin group ID '00000000-0000-0000-0000-000000000001' to be in the list"
  }

  assert {
    condition = contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "00000000-0000-0000-0000-000000000002"
    )
    error_message = "Expected: admin group ID '00000000-0000-0000-0000-000000000002' to be in the list"
  }

  assert {
    condition     = module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].azure_rbac_enabled == false
    error_message = "Expected: azure_rbac_enabled to be false by default"
  }
}

# Test case 2: Verify AAD is disabled when aks_aad_enabled is not "true"
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
    error_message = "Expected: AAD block should not exist when not enabled \n Actual: AAD block exists"
  }
}

# Test case 3: Verify AAD is disabled when aks_aad_enabled is "false"
run "valid_aad_explicitly_disabled" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : "false"
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 0
    error_message = "Expected: AAD block should not exist when explicitly disabled \n Actual: AAD block exists"
  }
}

# Test case 4: Verify single admin group works
run "valid_single_admin_group" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : "true",
      "aks_aad_admin_group_object_ids" : "00000000-0000-0000-0000-000000000001"
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids) == 1
    error_message = "Expected: 1 admin group \n Actual: ${length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids)}"
  }

  assert {
    condition = contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "00000000-0000-0000-0000-000000000001"
    )
    error_message = "Expected: admin group ID '00000000-0000-0000-0000-000000000001' to be in the list"
  }
}

# Test case 5: Verify AAD enabled but no admin groups provided (empty list)
run "valid_aad_enabled_no_admin_groups" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : "true"
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) > 0
    error_message = "Expected: AAD block to exist when enabled"
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids) == 0
    error_message = "Expected: 0 admin groups when not provided \n Actual: ${length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids)}"
  }
}

# Test case 6: Verify override of tfvars AAD config with json_input
run "valid_override_tfvars_aad_config" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : "true",
      "aks_aad_admin_group_object_ids" : "11111111-1111-1111-1111-111111111111"
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
        azure_active_directory_role_based_access_control = {
          tenant_id              = null
          admin_group_object_ids = ["22222222-2222-2222-2222-222222222222"]
          azure_rbac_enabled     = false
        }
      }
    ]
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) > 0
    error_message = "Expected: AAD block to exist when enabled"
  }

  assert {
    condition = contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "11111111-1111-1111-1111-111111111111"
    )
    error_message = "Expected: json_input should override tfvars config. Admin group should be from json_input"
  }

  assert {
    condition = !contains(
      module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control[0].admin_group_object_ids,
      "22222222-2222-2222-2222-222222222222"
    )
    error_message = "Expected: tfvars admin group should be overridden and not present"
  }
}
