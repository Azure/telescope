variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus",
    "public_key_path" : "public_key_path",
    "aks_network_dataplane" : "cilium",
    "aks_network_policy" : "cilium"
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

run "valid_override_network_data_plane" {

  command = plan

  assert {
    condition     = module.aks["test"].aks_cluster.network_profile[0].network_data_plane == "cilium"
    error_message = "Expected: 'cilium' \n Actual:  ${module.aks["test"].aks_cluster.network_profile[0].network_data_plane}"
  }
}

run "valid_no_override_network_data_plane" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
    }
  }

  assert {
    condition     = module.aks["test"].aks_cluster.network_profile[0].network_data_plane == var.aks_config_list[0].network_profile.network_dataplane
    error_message = "Expected: ${var.aks_config_list[0].network_profile.network_dataplane} \n Actual:  ${module.aks["test"].aks_cluster.network_profile[0].network_data_plane}"
  }
}

run "valid_aks_network_policy_and_dataplane_no_match_fails_1" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_network_dataplane" : "cilium"
      "aks_network_policy" : "azure"
    }
  }

  expect_failures = [var.json_input.aks_network_policy]
}

run "valid_aks_network_policy_and_dataplane_no_match_fails_2" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_network_dataplane" : "azure"
      "aks_network_policy" : "cilium"
    }
  }

  expect_failures = [var.json_input.aks_network_policy]
}


run "valid_aks_network_policy_ok" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
      "aks_network_policy" : "cilium"
    }
  }

  assert {
    condition     = module.aks["test"].aks_cluster.network_profile[0].network_policy == "cilium"
    error_message = "Expected: 'cilium' \n Actual:  ${module.aks["test"].aks_cluster.network_profile[0].network_policy}"
  }
}

run "valid_no_network_policy_and_dataplane_defined" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
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

  assert {
    condition     = module.aks["test"].aks_cluster.network_profile[0].network_data_plane == "azure"
    error_message = "Expected: 'azure' (default) \n Actual:  ${module.aks["test"].aks_cluster.network_profile[0].network_data_plane}"
  }

  # Note: The network_policy attribute is assigned a value only during the resource creation (apply) phase.
  # Therefore, it cannot be tested during the planning phase as its value is not available until the resources are created.
}