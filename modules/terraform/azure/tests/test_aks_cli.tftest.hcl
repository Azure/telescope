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
  }

  aks_cli_config_list = [
    {
      role                          = "client"
      aks_name                      = "test"
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


# This test case verifies the AKS CLI command generation when no optional parameters are provided.
# It ensures that the generated command matches the expected format and includes all required parameters.
run "test_aws_cli2" {

  command = apply

  assert {
    # Check if the generated command matches the expected AKS CLI command format
    condition = length(regex(
      "az aks create -g 123456789 -n test --location eastus --tier Standard --tags SkipAKSCluster=1 creation_time=.* deletion_due_time=.* owner=aks role=client run_id=123456789 scenario=perf-eval-my_scenario --no-ssh-key --enable-managed-identity --nodepool-name default --node-count 2 --node-vm-size Standard_D2s_v3 --vm-set-type VirtualMachineScaleSets$",
      replace(module.aks-cli["client"].aks_cli_command, "/\\s+/", " ") # normalize whitespace for comparison
    )) > 0
    error_message = "Actual: ${replace(module.aks-cli["client"].aks_cli_command, "\\s+", " ")}"
  }
}

run "test_aws_cli_automatic" {

  command = apply

  variables {

    aks_cli_config_list = [
      {
        role                          = "client"
        aks_name                      = "test"
        sku_tier                      = "Standard"
        use_aks_preview_cli_extension = true
        optional_parameters = [
          {
            name  = "sku"
            value = "automatic"
          },
          {
            name  = "zones"
            value = "1 2 3"
          }
        ]
        dry_run = true
      }
    ]
  }

  assert {
    condition = length(regex(
      "az aks create -g 123456789 -n test --location eastus --tier Standard --tags SkipAKSCluster=1 creation_time=.* deletion_due_time=.* owner=aks role=client run_id=123456789 scenario=perf-eval-my_scenario --no-ssh-key --sku automatic --zones 1 2 3 --enable-managed-identity$",
      replace(module.aks-cli["client"].aks_cli_command, "/\\s+/", " ") # normalize whitespace for comparison
    )) > 0
    error_message = "Actual: ${replace(module.aks-cli["client"].aks_cli_command, "/\\s+/", " ")}"
  }
}

# Test that role assignments are NOT created when grant_rbac_permissions is false (default)
run "test_rbac_permissions_disabled" {

  command = plan

  variables {
    aks_cli_config_list = [
      {
        role                   = "client"
        aks_name               = "test"
        sku_tier               = "Standard"
        grant_rbac_permissions = false
        dry_run                = true
      }
    ]
  }

  assert {
    condition     = length(module.aks-cli["client"].role_assignments) == 0
    error_message = "Local role_assignments should be empty when grant_rbac_permissions is false. Actual count: ${length(module.aks-cli["client"].role_assignments)}"
  }

  assert {
    condition     = length(keys(module.aks-cli["client"].role_assignment_resources)) == 0
    error_message = "Role assignment resources should not be created when grant_rbac_permissions is false. Actual count: ${length(keys(module.aks-cli["client"].role_assignment_resources))}"
  }
}

# Test that role assignments are NOT created when grant_rbac_permissions is not specified (default behavior)
run "test_rbac_permissions_default" {

  command = plan

  variables {
    aks_cli_config_list = [
      {
        role     = "client"
        aks_name = "test"
        sku_tier = "Standard"
        dry_run  = true
      }
    ]
  }

  assert {
    condition     = length(module.aks-cli["client"].role_assignments) == 0
    error_message = "Local role_assignments should be empty when grant_rbac_permissions is not specified (defaults to false). Actual count: ${length(module.aks-cli["client"].role_assignments)}"
  }

  assert {
    condition     = length(keys(module.aks-cli["client"].role_assignment_resources)) == 0
    error_message = "Role assignment resources should not be created when grant_rbac_permissions is not specified (defaults to false). Actual count: ${length(keys(module.aks-cli["client"].role_assignment_resources))}"
  }
}

# Test that role assignments ARE created when grant_rbac_permissions is true
run "test_rbac_permissions_enabled" {

  command = plan

  variables {
    aks_cli_config_list = [
      {
        role                   = "client"
        aks_name               = "test"
        sku_tier               = "Standard"
        grant_rbac_permissions = true
        dry_run                = true
      }
    ]
  }

  assert {
    condition     = length(module.aks-cli["client"].role_assignments) == 2
    error_message = "Local role_assignments should contain 2 assignments (aks_contributor and aks_cluster_admin) when grant_rbac_permissions is true. Actual count: ${length(module.aks-cli["client"].role_assignments)}"
  }

  assert {
    condition     = length(keys(module.aks-cli["client"].role_assignment_resources)) == 2
    error_message = "Role assignment resources should be created when grant_rbac_permissions is true. Actual count: ${length(keys(module.aks-cli["client"].role_assignment_resources))}"
  }

  assert {
    condition     = contains(keys(module.aks-cli["client"].role_assignments), "aks_contributor")
    error_message = "Role assignments should include aks_contributor when grant_rbac_permissions is true"
  }

  assert {
    condition     = contains(keys(module.aks-cli["client"].role_assignments), "aks_cluster_admin")
    error_message = "Role assignments should include aks_cluster_admin when grant_rbac_permissions is true"
  }
}

# Test role assignment configuration details when enabled
run "test_rbac_permissions_configuration" {

  command = plan

  variables {
    aks_cli_config_list = [
      {
        role                   = "client"
        aks_name               = "test"
        sku_tier               = "Standard"
        grant_rbac_permissions = true
        dry_run                = true
      }
    ]
  }

  assert {
    condition     = module.aks-cli["client"].role_assignments["aks_contributor"].role_definition_name == "Contributor"
    error_message = "AKS Contributor role assignment should have role_definition_name set to 'Contributor'. Actual: ${module.aks-cli["client"].role_assignments["aks_contributor"].role_definition_name}"
  }

  assert {
    condition     = module.aks-cli["client"].role_assignments["aks_cluster_admin"].role_definition_name == "Azure Kubernetes Service RBAC Cluster Admin"
    error_message = "AKS Cluster Admin role assignment should have role_definition_name set to 'Azure Kubernetes Service RBAC Cluster Admin'. Actual: ${module.aks-cli["client"].role_assignments["aks_cluster_admin"].role_definition_name}"
  }

  assert {
    condition     = can(regex("^/subscriptions/.*/resourceGroups/123456789$", module.aks-cli["client"].role_assignments["aks_contributor"].scope))
    error_message = "AKS Contributor scope should match the resource group pattern. Actual: ${module.aks-cli["client"].role_assignments["aks_contributor"].scope}"
  }

  assert {
    condition     = module.aks-cli["client"].role_assignments["aks_contributor"].role_name == "AKS Contributor"
    error_message = "AKS Contributor role assignment should have role_name set to 'AKS Contributor'. Actual: ${module.aks-cli["client"].role_assignments["aks_contributor"].role_name}"
  }

  assert {
    condition     = module.aks-cli["client"].role_assignments["aks_cluster_admin"].role_name == "AKS Cluster Admin"
    error_message = "AKS Cluster Admin role assignment should have role_name set to 'AKS Cluster Admin'. Actual: ${module.aks-cli["client"].role_assignments["aks_cluster_admin"].role_name}"
  }
}
