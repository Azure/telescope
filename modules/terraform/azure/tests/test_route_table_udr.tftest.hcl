variables {
  scenario_type  = "perf-eval"
  scenario_name  = "route_table_test"
  deletion_delay = "1h"
  owner          = "aks"
  json_input = {
    "run_id" : "test-route-table-123",
    "region" : "eastus"
  }

  network_config_list = [
    {
      role               = "test-network"
      vnet_name          = "test-vnet"
      vnet_address_space = "10.0.0.0/16"
      subnet = [
        {
          name           = "aks-subnet"
          address_prefix = "10.0.1.0/24"
        },
        {
          name           = "firewall-subnet"
          address_prefix = "10.0.2.0/24"
        }
      ]
      network_security_group_name = ""
      nic_public_ip_associations  = []
      nsr_rules                   = []
      route_tables = [
        {
          name                          = "test-route-table"
          bgp_route_propagation_enabled = true
          routes = [
            {
              name                   = "internet-route"
              address_prefix         = "0.0.0.0/0"
              next_hop_type          = "VirtualAppliance"
              next_hop_in_ip_address = "10.0.2.4"
            },
            {
              name           = "local-vnet"
              address_prefix = "10.0.0.0/16"
              next_hop_type  = "VnetLocal"
            }
          ]
          subnet_associations = [
            {
              subnet_name = "aks-subnet"
            }
          ]
        }
      ]
    }
  ]

  aks_config_list = [
    {
      role        = "test-udr"
      aks_name    = "test-udr-cluster"
      dns_prefix  = "testudr"
      subnet_name = "aks-subnet"
      sku_tier    = "Standard"
      network_profile = {
        network_plugin = "azure"
        outbound_type  = "userDefinedRouting"
        pod_cidr       = "10.244.0.0/16"
        service_cidr   = "10.245.0.0/16"
        dns_service_ip = "10.245.0.10"
      }
      default_node_pool = {
        name                         = "system"
        node_count                   = 1
        vm_size                      = "Standard_D2s_v3"
        os_disk_type                 = "Managed"
        only_critical_addons_enabled = false
        temporary_name_for_rotation  = "systemtmp"
      }
      extra_node_pool = []
    }
  ]
}

run "route_table_created" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "single-route"
        vnet_name          = "test-vnet-single"
        vnet_address_space = "10.1.0.0/16"
        subnet = [
          {
            name           = "test-subnet"
            address_prefix = "10.1.1.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "single-route-rt"
            bgp_route_propagation_enabled = true
            routes = [
              {
                name           = "internet-direct"
                address_prefix = "0.0.0.0/0"
                next_hop_type  = "Internet"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "test-subnet"
              }
            ]
          }
        ]
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create one virtual network"
  }
}

run "subnet_association_created" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "assoc-test"
        vnet_name          = "test-vnet-assoc"
        vnet_address_space = "10.6.0.0/16"
        subnet = [
          {
            name           = "associated-subnet"
            address_prefix = "10.6.1.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "assoc-rt"
            bgp_route_propagation_enabled = true
            routes = [
              {
                name           = "test-route"
                address_prefix = "192.168.0.0/16"
                next_hop_type  = "VnetLocal"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "associated-subnet"
              }
            ]
          }
        ]
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network with subnet association"
  }
}

run "route_table_with_virtual_appliance" {
  command = plan

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network with route table"
  }
}

run "multiple_route_tables" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "multi-rt"
        vnet_name          = "test-vnet-multi"
        vnet_address_space = "10.2.0.0/16"
        subnet = [
          {
            name           = "subnet-1"
            address_prefix = "10.2.1.0/24"
          },
          {
            name           = "subnet-2"
            address_prefix = "10.2.2.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "route-table-1"
            bgp_route_propagation_enabled = true
            routes = [
              {
                name                   = "to-firewall"
                address_prefix         = "0.0.0.0/0"
                next_hop_type          = "VirtualAppliance"
                next_hop_in_ip_address = "10.2.0.4"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "subnet-1"
              }
            ]
          },
          {
            name                          = "route-table-2"
            bgp_route_propagation_enabled = false
            routes = [
              {
                name           = "direct-internet"
                address_prefix = "0.0.0.0/0"
                next_hop_type  = "Internet"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "subnet-2"
              }
            ]
          }
        ]
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network with multiple route tables"
  }
}

run "aks_with_udr" {
  command = plan

  assert {
    condition     = length(module.aks) == 1
    error_message = "Should create AKS cluster with UDR"
  }

  assert {
    condition     = module.aks["test-udr"].aks_cluster.network_profile[0].outbound_type == "userDefinedRouting"
    error_message = "AKS should use userDefinedRouting outbound type"
  }
}

run "route_table_without_bgp_propagation" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "no-bgp"
        vnet_name          = "test-vnet-nobgp"
        vnet_address_space = "10.3.0.0/16"
        subnet = [
          {
            name           = "test-subnet"
            address_prefix = "10.3.1.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "no-bgp-rt"
            bgp_route_propagation_enabled = false
            routes = [
              {
                name           = "static-route"
                address_prefix = "192.168.0.0/16"
                next_hop_type  = "VnetLocal"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "test-subnet"
              }
            ]
          }
        ]
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network with BGP propagation disabled"
  }
}

run "route_table_with_multiple_routes" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "complex-routes"
        vnet_name          = "test-vnet-complex"
        vnet_address_space = "10.4.0.0/16"
        subnet = [
          {
            name           = "app-subnet"
            address_prefix = "10.4.1.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
        route_tables = [
          {
            name                          = "complex-rt"
            bgp_route_propagation_enabled = true
            routes = [
              {
                name                   = "to-hub"
                address_prefix         = "10.100.0.0/16"
                next_hop_type          = "VirtualAppliance"
                next_hop_in_ip_address = "10.4.0.4"
              },
              {
                name                   = "to-internet"
                address_prefix         = "0.0.0.0/0"
                next_hop_type          = "VirtualAppliance"
                next_hop_in_ip_address = "10.4.0.4"
              },
              {
                name           = "local-vnet"
                address_prefix = "10.4.0.0/16"
                next_hop_type  = "VnetLocal"
              },
              {
                name           = "blackhole"
                address_prefix = "192.168.100.0/24"
                next_hop_type  = "None"
              }
            ]
            subnet_associations = [
              {
                subnet_name = "app-subnet"
              }
            ]
          }
        ]
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network with complex routing"
  }
}

run "no_route_tables" {
  command = plan

  variables {
    network_config_list = [
      {
        role               = "no-rt"
        vnet_name          = "test-vnet-no-rt"
        vnet_address_space = "10.5.0.0/16"
        subnet = [
          {
            name           = "default-subnet"
            address_prefix = "10.5.1.0/24"
          }
        ]
        network_security_group_name = ""
        nic_public_ip_associations  = []
        nsr_rules                   = []
      }
    ]
    aks_config_list = []
  }

  assert {
    condition     = length(module.virtual_network) == 1
    error_message = "Should create virtual network without route tables"
  }
}
