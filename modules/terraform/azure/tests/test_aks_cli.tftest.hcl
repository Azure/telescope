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
