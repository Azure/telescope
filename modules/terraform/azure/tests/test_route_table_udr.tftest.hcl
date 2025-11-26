variables {
  scenario_type  = "perf-eval"
  scenario_name  = "route_table_test"
  deletion_delay = "1h"
  owner          = "aks"
  json_input = {
    "run_id" : "test",
    "region" : "eastus"
  }

  network_config_list = [
    {
      role                        = "test"
      vnet_name                   = "test-vnet"
      vnet_address_space          = "10.0.0.0/16"
      subnet                      = [{ name = "test-subnet", address_prefix = "10.0.1.0/24" }]
      network_security_group_name = ""
      nic_public_ip_associations  = []
      nsr_rules                   = []
      route_tables = [
        {
          name                          = "test-rt"
          bgp_route_propagation_enabled = true
          routes                        = [{ name = "internet", address_prefix = "0.0.0.0/0", next_hop_type = "Internet" }]
          subnet_associations           = [{ subnet_name = "test-subnet" }]
        }
      ]
    }
  ]

  aks_config_list = []
}

run "route_table_created" {
  command = plan

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Expected: 1 virtual network\nActual: ${length(module.virtual_network)}"
  }

  assert {
    condition     = length(keys(module.virtual_network["test"].route_tables)) == 1
    error_message = "Expected: 1 route table\nActual: ${length(keys(module.virtual_network["test"].route_tables))}"
  }

  assert {
    condition     = contains(module.virtual_network["test"].route_tables["test-rt"], "test-subnet")
    error_message = "Expected route table to be associated with test-subnet"
  }
}

run "route_table_with_firewall" {
  command = plan

  variables {
    network_config_list = [
      {
        role                        = "test"
        vnet_name                   = "test-vnet"
        vnet_address_space          = "10.0.0.0/16"
        subnet                      = [{ name = "test-subnet", address_prefix = "10.0.1.0/24" }]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "fw-rt"
            bgp_route_propagation_enabled = false
            routes                        = [{ name = "force-tunnel", address_prefix = "0.0.0.0/0", next_hop_type = "VirtualAppliance", next_hop_in_ip_address = "10.0.0.4" }]
            subnet_associations           = [{ subnet_name = "test-subnet" }]
          }
        ]
      }
    ]
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Expected: 1 virtual network\nActual: ${length(module.virtual_network)}"
  }

  assert {
    condition     = length(module.virtual_network["test"].route_tables["fw-rt"]) == 1
    error_message = "Expected: 1 subnet association\nActual: ${length(module.virtual_network["test"].route_tables["fw-rt"])}"
  }

  assert {
    condition     = contains(module.virtual_network["test"].route_tables["fw-rt"], "test-subnet")
    error_message = "Expected route table to be associated with test-subnet"
  }
}

run "no_route_tables" {
  command = plan

  variables {
    network_config_list = [
      {
        role                        = "test"
        vnet_name                   = "test-vnet"
        vnet_address_space          = "10.0.0.0/16"
        subnet                      = [{ name = "test-subnet", address_prefix = "10.0.1.0/24" }]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
      }
    ]
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Expected: 1 virtual network\nActual: ${length(module.virtual_network)}"
  }

  assert {
    condition     = length(keys(module.virtual_network["test"].route_tables)) == 0
    error_message = "Expected: 0 route tables\nActual: ${length(keys(module.virtual_network["test"].route_tables))}"
  }
}
