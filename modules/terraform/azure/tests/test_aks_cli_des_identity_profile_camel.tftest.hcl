mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000000"
      subscription_id = "12345678-1234-1234-1234-123456789012"
    }
  }
}

mock_provider "azapi" {
  source = "./tests"

  mock_data "azapi_resource" {
    defaults = {
      output = {
        identity = {
          principalId = "00000000-0000-0000-0000-000000000111"
        }
        properties = {
          identityProfile = {
            kubeletIdentity = {
              objectId = "00000000-0000-0000-0000-000000000222"
            }
          }
        }
      }
    }
  }
}

variables {
  scenario_type  = "perf-eval"
  scenario_name  = "des-test"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus"
  }

  aks_cli_config_list = [
    {
      role                          = "client"
      aks_name                      = "test"
      sku_tier                      = "Standard"
      use_aks_preview_cli_extension = false
      default_node_pool = {
        name       = "default"
        node_count = 2
        vm_size    = "Standard_D2s_v3"
      }
      disk_encryption_set_name = "des-1"
      dry_run                  = false
    }
  ]

  key_vault_config_list = [
    {
      name = "kvdes"
      keys = [
        {
          key_name = "key1"
        }
      ]
    }
  ]

  disk_encryption_set_config_list = [
    {
      name           = "des-1"
      key_vault_name = "kvdes"
      key_name       = "key1"
    }
  ]
}

run "aks_cli_des_identity_profile_camel" {
  command = plan

  assert {
    condition     = module.aks-cli["client"].azurerm_role_assignment.des_reader_kubelet[0].principal_id == "00000000-0000-0000-0000-000000000222"
    error_message = "Expected kubelet identity principalId to match azapi mock output"
  }

  assert {
    condition     = module.aks-cli["client"].azurerm_role_assignment.des_reader_cluster[0].principal_id == "00000000-0000-0000-0000-000000000111"
    error_message = "Expected cluster identity principalId to match azapi mock output"
  }
}
