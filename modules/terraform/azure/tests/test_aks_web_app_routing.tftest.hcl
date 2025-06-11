variables {
  scenario_type  = "perf-eval"
  scenario_name  = "aks_web_app_routing_test"
  deletion_delay = "2h"
  owner          = "aks"
  
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus",
    "public_key_path" : "public_key_path"
  }

  # DNS zones for web app routing
  dns_zones = [
    {
      name = "webapp.example.com"
    },
    {
      name = "api.example.com"
    }
  ]

  # AKS configuration with web app routing
  aks_config_list = [
    {
      role        = "test-1"
      aks_name    = "test-aks-webapp"
      dns_prefix  = "test-webapp"
      subnet_name = "test-subnet-1"
      sku_tier    = "Standard"
      network_profile = {
        network_plugin      = "azure"
        network_plugin_mode = "overlay"
      }
      default_node_pool = {
        name                         = "default"
        node_count                   = 1
        vm_size                      = "Standard_D2s_v3"
        os_disk_type                 = "Managed"
        os_disk_size_gb              = 128
        only_critical_addons_enabled = false
        temporary_name_for_rotation  = "defaulttmp"
      }
      extra_node_pool = []
      web_app_routing = {
        dns_zone_names = ["webapp.example.com", "api.example.com"]
      }
    }
  ]
}

run "aks_web_app_routing_enabled" {
  command = plan

  # Verify AKS cluster is created with web app routing
  assert {
    condition     = length(module.aks["test-1"].aks_cluster.web_app_routing) > 0
    error_message = "Web app routing should be enabled on AKS cluster"
  }
}

run "aks_web_app_routing_dns_zone_contributor_role" {
  command = plan

  # Verify DNS Zone Contributor role assignments are created for each DNS zone
  assert {
    condition     = length(module.aks["test-1"].dns_zone_contributor_role_assignments) == 2
    error_message = "DNS Zone Contributor role assignments should be created for web app routing"
  }
}

run "aks_web_app_routing_disabled" {
  command = plan

  variables {
    aks_config_list = [
      {
        role        = "test-2"
        aks_name    = "test-aks-no-webapp"
        dns_prefix  = "test-no-webapp"
        subnet_name = "test-subnet-1"
        sku_tier    = "Standard"
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 1
          vm_size                      = "Standard_D2s_v3"
          os_disk_type                 = "Managed"
          os_disk_size_gb              = 128
          only_critical_addons_enabled = false
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
        # No web_app_routing configuration
      }
    ]
  }

  # Verify web app routing is not enabled when not configured
  assert {
    condition     = length(module.aks["test-2"].aks_cluster.web_app_routing) == 0
    error_message = "Web app routing should not be enabled when not configured"
  }
}

run "aks_web_app_routing_invalid_dns_zone_reference" {
  # This test documents expected error behavior when web_app_routing 
  # references DNS zones that don't exist. This test will fail with:
  # "Invalid index: The given key does not identify an element in this collection value"
  # This is the expected behavior and validates proper error handling.
  command = plan

  variables {
    dns_zones = [
      {
        name = "valid.example.com"
      }
    ]
    aks_config_list = [
      {
        role        = "test-5"
        aks_name    = "test-aks-invalid-dns"
        dns_prefix  = "test-invalid-dns"
        subnet_name = "test-subnet-1"
        sku_tier    = "Standard"
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 1
          vm_size                      = "Standard_D2s_v3"
          os_disk_type                 = "Managed"
          os_disk_size_gb              = 128
          only_critical_addons_enabled = false
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
        web_app_routing = {
          dns_zone_names = ["nonexistent.example.com"]  # This DNS zone doesn't exist
        }
      }
    ]
  }

  # NOTE: This test is expected to fail during terraform plan
  # Remove this test from normal test runs, it's for documentation only
}

run "aks_web_app_routing_partial_dns_zone_usage" {
  command = plan

  variables {
    # Create additional DNS zone to test partial usage
    dns_zones = [
      {
        name = "webapp.example.com"
      },
      {
        name = "api.example.com"
      },
      {
        name = "admin.example.com"
      }
    ]
    aks_config_list = [
      {
        role        = "test-6"
        aks_name    = "test-aks-partial-dns"
        dns_prefix  = "test-partial-dns"
        subnet_name = "test-subnet-1"
        sku_tier    = "Standard"
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 1
          vm_size                      = "Standard_D2s_v3"
          os_disk_type                 = "Managed"
          os_disk_size_gb              = 128
          only_critical_addons_enabled = false
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
        web_app_routing = {
          dns_zone_names = ["admin.example.com"]  # Only using one of the three DNS zones
        }
      }
    ]
  }

  # Verify all DNS zones are still created
  assert {
    condition     = length(module.dns_zones.dns_zone_ids) == 3
    error_message = "All 3 DNS zones should still be created regardless of AKS usage"
  }

  # Verify AKS has web app routing enabled
  assert {
    condition     = length(module.aks["test-6"].aks_cluster.web_app_routing) > 0
    error_message = "AKS cluster should have web app routing enabled with partial DNS zone usage"
  }
}

run "aks_web_app_routing_empty_dns_zone_names" {
  command = plan

  variables {
    dns_zones = [
      {
        name = "webapp.example.com"
      },
      {
        name = "api.example.com"
      }
    ]
    aks_config_list = [
      {
        role        = "test-7"
        aks_name    = "test-aks-empty-dns-names"
        dns_prefix  = "test-empty-dns-names"
        subnet_name = "test-subnet-1"
        sku_tier    = "Standard"
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 1
          vm_size                      = "Standard_D2s_v3"
          os_disk_type                 = "Managed"
          os_disk_size_gb              = 128
          only_critical_addons_enabled = false
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
        web_app_routing = {
          dns_zone_names = []  # Empty DNS zone names list
        }
      }
    ]
  }

  # Verify web app routing is enabled when dns_zone_names is empty
  assert {
    condition     = length(module.aks["test-7"].aks_cluster.web_app_routing) > 0
    error_message = "Web app routing should be enabled even when dns_zone_names is empty"
  }

  # Verify DNS zones are still created even though not used
  assert {
    condition     = length(module.dns_zones.dns_zone_ids) == 2
    error_message = "DNS zones should still be created even when not referenced by AKS"
  }
}