variables {
  scenario_type  = "perf-eval"
  scenario_name  = "dns_zone_test"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus",
    "public_key_path" : "public_key_path"
  }

  # Test DNS zones configuration
  dns_zones = [
    {
      name = "single.example.com"
    }
  ]
}

run "dns_zone_creation_single_zone" {
  command = plan

  # Verify single DNS zone is created
  assert {
    condition     = length(module.dns_zones.dns_zone_ids) == 1
    error_message = "Expected 1 DNS zone to be created, got ${length(module.dns_zones.dns_zone_ids)}"
  }
}

run "dns_zone_creation_multiple_zones" {
  command = plan

  variables {
    dns_zones = [
      {
        name = "example1.com"
      },
      {
        name = "example2.com"
      },
      {
        name = "test.local"
      }
    ]
  }

  # Verify multiple DNS zones are created
  assert {
    condition     = length(module.dns_zones.dns_zone_ids) == 3
    error_message = "Expected 3 DNS zones, got ${length(module.dns_zones.dns_zone_ids)}"
  }
}

run "dns_zone_empty_list" {
  command = plan

  variables {
    dns_zones = []
  }

  # Verify no DNS zones are created when list is empty
  assert {
    condition     = length(module.dns_zones.dns_zone_ids) == 0
    error_message = "Expected 0 DNS zones when list is empty, got ${length(module.dns_zones.dns_zone_ids)}"
  }
}