mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000000"
      object_id = "12345678-1234-5678-9abc-def012345678"
    }
  }
}

# Command assertions use dry_run; do not install CLI extensions during tests.
override_resource {
  target = module.aks-cli["client"].terraform_data.enable_aks_cli_preview_extension[0]
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
    condition     = module.aks["test"].aks_cluster.local_account_disabled
    error_message = "Expected: local accounts disabled with AAD"
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

# Test case 2: Verify AAD is enabled when aks_aad_enabled is not set
run "valid_aad_default" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 1 && module.aks["test"].aks_cluster.local_account_disabled
    error_message = "Expected: AAD enabled and local accounts disabled by default"
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
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 0 && module.aks["test"].aks_cluster.local_account_disabled
    error_message = "Expected: AAD absent but local accounts always disabled"
  }
}

# ============================================================================
# AAD Integration Tests for aks-cli module
# ============================================================================

# Test case 4: Verify AAD parameters are correctly generated in aks-cli when enabled
run "valid_aks_cli_aad_enabled" {

  command = apply

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : true
    }

    aks_config_list = []

    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test-aad-cli"
        sku_tier                      = "Standard"
        use_aks_preview_cli_extension = true
        default_node_pool = {
          name       = "default"
          node_count = 2
          vm_size    = "Standard_D2s_v3"
        }
        optional_parameters = []
        dry_run             = true
      }
    ]
  }

  # Verify the CLI command includes --enable-aad flag
  assert {
    condition     = can(regex("--enable-aad", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should include --enable-aad flag\nActual: ${module.aks-cli["client"].aks_cli_command}"
  }

  # Verify the CLI command includes --enable-azure-rbac flag
  assert {
    condition     = can(regex("--enable-azure-rbac", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should include --enable-azure-rbac flag\nActual: ${module.aks-cli["client"].aks_cli_command}"
  }

  # Verify the CLI command includes --aad-admin-group-object-ids with the mocked object_id
  assert {
    condition     = can(regex("--aad-admin-group-object-ids 12345678-1234-5678-9abc-def012345678", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should include --aad-admin-group-object-ids with correct object_id\nActual: ${module.aks-cli["client"].aks_cli_command}"
  }

  # Verify the CLI command includes --aad-tenant-id with the mocked tenant_id
  assert {
    condition     = can(regex("--aad-tenant-id 00000000-0000-0000-0000-000000000000", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should include --aad-tenant-id with correct tenant_id\nActual: ${module.aks-cli["client"].aks_cli_command}"
  }
}

# Test case 5: Verify AAD parameters are omitted in aks-cli when disabled
run "valid_aks_cli_aad_disabled" {

  command = apply

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : false
    }

    aks_config_list = []

    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test-no-aad-cli"
        sku_tier                      = "Standard"
        use_aks_preview_cli_extension = true
        default_node_pool = {
          name       = "default"
          node_count = 2
          vm_size    = "Standard_D2s_v3"
        }
        optional_parameters = []
        dry_run             = true
      }
    ]
  }

  # Verify the CLI command does NOT include --enable-aad flag
  assert {
    condition     = !can(regex("--enable-aad", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should NOT include --enable-aad flag when disabled\nActual: ${module.aks-cli["client"].aks_cli_command}"
  }

  # Verify the CLI command does NOT include any AAD-related flags
  assert {
    condition     = !can(regex("--aad-", module.aks-cli["client"].aks_cli_command)) && can(regex("--disable-local-accounts", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: no AAD flags but local accounts always disabled"
  }
}

# Test case 6: Verify null also uses the enabled default (omitted inputs are covered by test_aks_cli)
run "valid_aks_cli_aad_null" {

  command = apply

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_aad_enabled" : null
    }

    aks_config_list = []

    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test-default-cli"
        sku_tier                      = "Standard"
        use_aks_preview_cli_extension = true
        default_node_pool = {
          name       = "default"
          node_count = 2
          vm_size    = "Standard_D2s_v3"
        }
        optional_parameters = []
        dry_run             = true
      }
    ]
  }

  assert {
    condition     = can(regex("--enable-aad", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: CLI command should include --enable-aad by default"
  }

  assert {
    condition     = can(regex("--enable-azure-rbac", module.aks-cli["client"].aks_cli_command)) && can(regex("--disable-local-accounts", module.aks-cli["client"].aks_cli_command))
    error_message = "Expected: Azure RBAC and disabled local accounts by default"
  }
}

run "valid_aad_null" {
  command = plan

  variables {
    json_input = {
      run_id          = "123456789"
      region          = "eastus"
      aks_aad_enabled = null
    }
  }

  assert {
    condition     = length(module.aks["test"].aks_cluster.azure_active_directory_role_based_access_control) == 1 && module.aks["test"].aks_cluster.local_account_disabled
    error_message = "Expected: explicit null uses the enabled AAD default"
  }
}
