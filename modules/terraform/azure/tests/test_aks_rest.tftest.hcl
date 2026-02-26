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

variables {
  scenario_type  = "perf-eval"
  scenario_name  = "test_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "test-rg-123",
    "region" : "uksouth",
  }

  aks_rest_config_list = [
    {
      role                       = "client"
      aks_name                   = "test-aks-rest"
      sku_tier                   = "Standard"
      sku_name                   = "Base"
      api_version                = "2026-01-02-preview"
      control_plane_scaling_size = "H2"
      kubernetes_version         = "1.33"
      network_plugin             = "azure"
      network_plugin_mode        = "overlay"
      default_node_pool = {
        name       = "systempool"
        mode       = "System"
        node_count = 3
        vm_size    = "Standard_D2s_v5"
        os_type    = "Linux"
      }
      dry_run = true
    }
  ]
}

# Test 1: Verify the az rest PUT command contains the correct REST API URL
run "test_az_rest_put_url" {

  command = apply

  assert {
    condition = can(regex(
      "az rest --method PUT --url .*/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/test-rg-123/providers/Microsoft.ContainerService/managedClusters/test-aks-rest\\?api-version=2026-01-02-preview",
      module.aks-rest["client"].az_rest_put_command
    ))
    error_message = "REST API URL is incorrect. Actual: ${module.aks-rest["client"].az_rest_put_command}"
  }
}

# Test 2: Verify Content-Type header is present
run "test_content_type_header" {

  command = apply

  assert {
    condition = can(regex(
      "--headers \"Content-Type=application/json\"",
      module.aks-rest["client"].az_rest_put_command
    ))
    error_message = "Missing Content-Type header. Actual: ${module.aks-rest["client"].az_rest_put_command}"
  }
}

# Test 3: Verify custom headers are passed when specified
run "test_custom_header" {

  command = apply

  variables {
    aks_rest_config_list = [
      {
        role                       = "client"
        aks_name                   = "test-aks-rest"
        sku_tier                   = "Standard"
        sku_name                   = "Base"
        api_version                = "2026-01-02-preview"
        control_plane_scaling_size = "H2"
        kubernetes_version         = "1.33"
        custom_headers             = ["EtcdServersOverrides=hyperscale"]
        default_node_pool = {
          name       = "systempool"
          mode       = "System"
          node_count = 3
          vm_size    = "Standard_D2s_v5"
          os_type    = "Linux"
        }
        dry_run = true
      }
    ]
  }

  assert {
    condition = can(regex(
      "--headers \"EtcdServersOverrides=hyperscale\"",
      module.aks-rest["client"].az_rest_put_command
    ))
    error_message = "Missing custom header EtcdServersOverrides. Actual: ${module.aks-rest["client"].az_rest_put_command}"
  }
}

# Test 4: Verify JSON body contains controlPlaneScalingProfile with H2
run "test_control_plane_scaling_profile" {

  command = apply

  assert {
    condition = can(regex(
      "controlPlaneScalingProfile",
      module.aks-rest["client"].request_body
    ))
    error_message = "Request body missing controlPlaneScalingProfile. Actual: ${module.aks-rest["client"].request_body}"
  }

  assert {
    condition = can(regex(
      "H2",
      module.aks-rest["client"].request_body
    ))
    error_message = "Request body missing scalingSize H2. Actual: ${module.aks-rest["client"].request_body}"
  }
}

# Test 5: Verify JSON body contains correct kubernetes version
run "test_kubernetes_version" {

  command = apply

  assert {
    condition = can(regex(
      "\"kubernetesVersion\":\"1.33\"",
      module.aks-rest["client"].request_body
    ))
    error_message = "Kubernetes version incorrect in request body. Actual: ${module.aks-rest["client"].request_body}"
  }
}

# Test 6: Verify JSON body contains correct agent pool profile
run "test_agent_pool_profile" {

  command = apply

  assert {
    condition = can(regex(
      "systempool",
      module.aks-rest["client"].request_body
    ))
    error_message = "Agent pool name 'systempool' not found in request body. Actual: ${module.aks-rest["client"].request_body}"
  }

  assert {
    condition = can(regex(
      "Standard_D2s_v5",
      module.aks-rest["client"].request_body
    ))
    error_message = "VM size 'Standard_D2s_v5' not found in request body. Actual: ${module.aks-rest["client"].request_body}"
  }
}

# Test 7: Verify JSON body contains correct SKU
run "test_sku" {

  command = apply

  assert {
    condition = can(regex(
      "\"name\":\"Base\"",
      module.aks-rest["client"].request_body
    ))
    error_message = "SKU name 'Base' not found in request body. Actual: ${module.aks-rest["client"].request_body}"
  }

  assert {
    condition = can(regex(
      "\"tier\":\"Standard\"",
      module.aks-rest["client"].request_body
    ))
    error_message = "SKU tier 'Standard' not found in request body. Actual: ${module.aks-rest["client"].request_body}"
  }
}

# Test 8: Verify delete command format
run "test_delete_command" {

  command = apply

  assert {
    condition = can(regex(
      "az aks delete -g test-rg-123 -n test-aks-rest --yes",
      module.aks-rest["client"].az_rest_delete_command
    ))
    error_message = "Delete command format incorrect. Actual: ${module.aks-rest["client"].az_rest_delete_command}"
  }
}

# Test 9: Verify az aks wait --created is chained after az rest PUT
run "test_wait_after_put" {

  command = apply

  assert {
    condition = can(regex(
      "&& az aks wait --created -g test-rg-123 -n test-aks-rest",
      module.aks-rest["client"].az_rest_put_command
    ))
    error_message = "Missing 'az aks wait --created' after PUT command. Actual: ${module.aks-rest["client"].az_rest_put_command}"
  }
}

# Test 10: Verify controlPlaneScalingProfile is NOT present when control_plane_scaling_size is null
run "test_without_control_plane_scaling" {

  command = apply

  variables {
    aks_rest_config_list = [
      {
        role               = "client"
        aks_name           = "test-aks-no-scaling"
        sku_tier           = "Standard"
        kubernetes_version = "1.33"
        default_node_pool = {
          name       = "default"
          node_count = 1
          vm_size    = "Standard_D2s_v3"
        }
        dry_run = true
      }
    ]
  }

  assert {
    condition = !can(regex(
      "controlPlaneScalingProfile",
      module.aks-rest["client"].request_body
    ))
    error_message = "controlPlaneScalingProfile should NOT be present when control_plane_scaling_size is null. Actual: ${module.aks-rest["client"].request_body}"
  }
}

# Test 11: Verify no custom headers flags when custom_headers is empty
run "test_without_custom_headers" {

  command = apply

  variables {
    aks_rest_config_list = [
      {
        role               = "client"
        aks_name           = "test-aks-no-headers"
        sku_tier           = "Standard"
        kubernetes_version = "1.33"
        custom_headers     = []
        default_node_pool = {
          name       = "default"
          node_count = 1
          vm_size    = "Standard_D2s_v3"
        }
        dry_run = true
      }
    ]
  }

  assert {
    condition = !can(regex(
      "EtcdServersOverrides",
      module.aks-rest["client"].az_rest_put_command
    ))
    error_message = "Custom headers should NOT be present when custom_headers is empty. Actual: ${module.aks-rest["client"].az_rest_put_command}"
  }
}
