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

  # Check that the route table resource will be created
  assert {
    condition     = length([for r in resource.changes : r if r.type == "azurerm_route_table" && r.change.actions[0] == "create"]) == 1
    error_message = "Expected: 1 route table to be created"
  }

  # Check that subnet association will be created
  assert {
    condition     = length([for r in resource.changes : r if r.type == "azurerm_subnet_route_table_association" && r.change.actions[0] == "create"]) == 1
    error_message = "Expected: 1 subnet route table association to be created"
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

  # Check that no route tables will be created
  assert {
    condition     = length([for r in resource.changes : r if r.type == "azurerm_route_table" && r.change.actions[0] == "create"]) == 0
    error_message = "Expected: 0 route tables to be created"
  }
}
