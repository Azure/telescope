mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      object_id       = "00000000-0000-0000-0000-000000000002"
      subscription_id = "00000000-0000-0000-0000-000000000003"
    }
  }
}
mock_provider "azapi" {}

variables {
  scenario_type = "perf-eval"
  scenario_name = "workload-acr"
  aks_config_list = [{
    role       = "client"
    aks_name   = "test-client"
    dns_prefix = "test-client"
    sku_tier   = "Standard"
    default_node_pool = {
      name                         = "default"
      node_count                   = 1
      vm_size                      = "Standard_D2s_v3"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = []
  }]
}

override_module {
  target = module.aks["client"]
  outputs = {
    kubelet_object_id = "00000000-0000-0000-0000-000000000004"
  }
}

run "default_no_grant" {
  command = plan
  variables {
    json_input = { run_id = "123456789", region = "eastus" }
  }
  assert {
    condition     = length(azurerm_role_assignment.workload_acr_pull) == 0
    error_message = "A workload registry grant must be opt-in."
  }
}

run "registry_subscription_scoped_pull" {
  command = plan
  variables {
    aks_cli_config_list = [{ role = "preview", aks_name = "test-preview", sku_tier = "Standard", dry_run = true }]
    json_input = {
      run_id          = "123456789"
      region          = "eastus"
      acr_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/testregistry"
    }

  }
  override_module {
    target = module.aks-cli["preview"]
  }
  assert {
    condition = (
      length(azurerm_role_assignment.workload_acr_pull) == 1 &&
      azurerm_role_assignment.workload_acr_pull["client"].principal_id == "00000000-0000-0000-0000-000000000004" &&
      azurerm_role_assignment.workload_acr_pull["client"].role_definition_name == "AcrPull" &&
      azurerm_role_assignment.workload_acr_pull["client"].scope == "/subscriptions/00000000-0000-0000-0000-000000000001"
    )
    error_message = "Only the real client kubelet should receive AcrPull on the registry's subscription; the dry-run cluster must be ignored."
  }
}

run "infer_cli_cluster" {
  command = plan
  variables {
    aks_config_list     = []
    aks_cli_config_list = [{ role = "pod2pod", aks_name = "test-network", sku_tier = "Standard" }]
    json_input = {
      run_id          = "123456789"
      region          = "eastus"
      acr_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/testregistry"
    }
  }
  override_module {
    target = module.aks-cli["pod2pod"]
    outputs = {
      kubelet_object_id = "00000000-0000-0000-0000-000000000005"
    }
  }
  assert {
    condition = (
      length(azurerm_role_assignment.workload_acr_pull) == 1 &&
      azurerm_role_assignment.workload_acr_pull["pod2pod"].principal_id == "00000000-0000-0000-0000-000000000005"
    )
    error_message = "The networking cluster's kubelet should receive AcrPull without an explicit selector."
  }
}

run "skip_when_no_cluster" {
  command = plan
  variables {
    aks_config_list = []
    json_input = {
      run_id          = "123456789"
      region          = "eastus"
      acr_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/testregistry"
    }
  }
  assert {
    condition     = length(azurerm_role_assignment.workload_acr_pull) == 0
    error_message = "A scenario without a cluster must not receive an AcrPull grant."
  }
}

run "skip_cli_dry_run" {
  command = plan
  variables {
    aks_config_list     = []
    aks_cli_config_list = [{ role = "pod2pod", aks_name = "test-network", sku_tier = "Standard", dry_run = true }]
    json_input = {
      run_id          = "123456789"
      region          = "eastus"
      acr_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ContainerRegistry/registries/testregistry"
    }
  }
  override_module {
    target = module.aks-cli["pod2pod"]
  }
  assert {
    condition     = length(azurerm_role_assignment.workload_acr_pull) == 0
    error_message = "A dry-run cluster must not receive an AcrPull grant."
  }
}
