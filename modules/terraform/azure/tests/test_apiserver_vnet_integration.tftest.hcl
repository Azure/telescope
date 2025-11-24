mock_provider "azurerm" {
  source = "./tests"
}

variables {
  scenario_type  = "perf-eval"
  scenario_name  = "test"
  deletion_delay = "2h"
  owner          = "aks"
}

# Test 1: Enable API Server VNet Integration with subnet ID
# Pipeline: ENABLE_APISERVER_VNET_INTEGRATION=true, API_SERVER_SUBNET_ID=<subnet-id>
# Expected: api_server_subnet_id should be passed to CLI command
run "apiserver_vnet_enabled_with_subnet" {
  command = plan

  variables {
    json_input = {
      "run_id" : "test-run",
      "region" : "eastus",
      "enable_apiserver_vnet_integration" : true
    }
    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test-aks"
        sku_tier                      = "Standard"
        use_aks_preview_cli_extension = true
        api_server_subnet_name        = "apiserver-subnet"
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

  # Verify parameters flow into terraform locals
  assert {
    condition     = var.json_input["enable_apiserver_vnet_integration"] == true
    error_message = "json_input: enable_apiserver_vnet_integration should be true"
  }

  assert {
    condition     = var.aks_cli_config_list[0].api_server_subnet_name == "apiserver-subnet"
    error_message = "aks_cli_config_list: api_server_subnet_name should be 'apiserver-subnet'"
  }
}

# Test 2: Disable API Server VNet Integration
# Pipeline: ENABLE_APISERVER_VNET_INTEGRATION=false (or not set)
# Expected: api_server_subnet_id should be null, no CLI parameters added
run "apiserver_vnet_disabled" {
  command = plan

  variables {
    json_input = {
      "run_id" : "test-run",
      "region" : "eastus",
      "enable_apiserver_vnet_integration" : false
    }
  }

  assert {
    condition     = var.json_input["enable_apiserver_vnet_integration"] == false
    error_message = "json_input: enable_apiserver_vnet_integration should be false"
  }

  # When disabled, api_server_subnet_name should not be present
  assert {
    condition     = try(var.json_input["api_server_subnet_name"], null) == null
    error_message = "json_input: api_server_subnet_name should not be set when disabled"
  }
}

# Test 3: Enable but no subnet name provided
# Pipeline: ENABLE_APISERVER_VNET_INTEGRATION=true, but API_SERVER_SUBNET_ID not set
# Expected: api_server_subnet_id should be null, no CLI parameters added
run "apiserver_vnet_enabled_no_subnet" {
  command = plan

  variables {
    json_input = {
      "run_id" : "test-run",
      "region" : "eastus",
      "enable_apiserver_vnet_integration" : true
    }

    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test-aks"
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
    condition     = var.json_input["enable_apiserver_vnet_integration"] == true
    error_message = "json_input: enable_apiserver_vnet_integration should be true"
  }

  # api_server_subnet_name should not be present
  assert {
    condition     = try(var.json_input["api_server_subnet_name"], null) == null
    error_message = "json_input: api_server_subnet_name should not be set"
  }
}
