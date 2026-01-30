mock_provider "azurerm" {
  source = "./tests"
}

variables {
  scenario_type  = "perf-eval"
  scenario_name  = "nap"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    run_id          = "test-123"
    region          = "eastus2"
    public_key_path = "/tmp/key.pub"
  }
  # Required main variables
  resource_group_name = "test-rg"
  location            = "eastus2"
  firewall_config = {
    name                 = "nap-firewall"
    sku_tier             = "Standard"
    subnet_id            = "/subscriptions/sub-id/resourceGroups/test-rg/providers/Microsoft.Network/virtualNetworks/test-vnet/subnets/AzureFirewallSubnet"
    public_ip_address_id = "/subscriptions/sub-id/resourceGroups/test-rg/providers/Microsoft.Network/publicIPAddresses/firewall-pip"
    threat_intel_mode    = "Alert"
    dns_proxy_enabled    = true

    application_rule_collections = [
      {
        name     = "allow-all"
        priority = 100
        action   = "Allow"
        rules = [
          {
            name             = "allow-all-traffic"
            source_addresses = ["*"]
            target_fqdns     = ["*"]
            protocols = [
              { port = "80", type = "Http" },
              { port = "443", type = "Https" }
            ]
          }
        ]
      }
    ]

    network_rule_collections = [
      {
        name     = "allow-all"
        priority = 100
        action   = "Allow"
        rules = [
          {
            name                  = "allow-all-traffic"
            source_addresses      = ["*"]
            destination_addresses = ["*"]
            destination_ports     = ["*"]
            protocols             = ["TCP", "UDP"]
          }
        ]
      }
    ]
  }
  tags = {
    environment = "test"
    owner       = "aks"
  }
}

run "firewall_with_allow_all_rules" {
  command = plan

  assert {
    condition     = var.firewall_config.name == "nap-firewall"
    error_message = "Firewall name should be nap-firewall"
  }

  assert {
    condition     = var.firewall_config.sku_tier == "Standard"
    error_message = "Firewall SKU tier should be Standard"
  }

  assert {
    condition     = var.firewall_config.threat_intel_mode == "Alert"
    error_message = "Threat intelligence mode should be Alert"
  }

  assert {
    condition     = var.firewall_config.dns_proxy_enabled == true
    error_message = "DNS proxy should be enabled"
  }
}

run "firewall_application_rules" {
  command = plan

  assert {
    condition     = length(var.firewall_config.application_rule_collections) == 1
    error_message = "Should have one application rule collection"
  }

  assert {
    condition     = var.firewall_config.application_rule_collections[0].name == "allow-all"
    error_message = "Application rule collection should be named allow-all"
  }

  assert {
    condition     = var.firewall_config.application_rule_collections[0].priority == 100
    error_message = "Application rule priority should be 100"
  }

  assert {
    condition     = length(var.firewall_config.application_rule_collections[0].rules) == 1
    error_message = "Should have one rule in application collection"
  }
}

run "firewall_network_rules" {
  command = plan

  assert {
    condition     = length(var.firewall_config.network_rule_collections) == 1
    error_message = "Should have one network rule collection"
  }

  assert {
    condition     = var.firewall_config.network_rule_collections[0].name == "allow-all"
    error_message = "Network rule collection should be named allow-all"
  }

  assert {
    condition     = var.firewall_config.network_rule_collections[0].action == "Allow"
    error_message = "Network rule action should be Allow"
  }
}

run "firewall_rule_protocols" {
  command = plan

  assert {
    condition     = contains(var.firewall_config.network_rule_collections[0].rules[0].protocols, "TCP")
    error_message = "Network rules should allow TCP"
  }

  assert {
    condition     = contains(var.firewall_config.network_rule_collections[0].rules[0].protocols, "UDP")
    error_message = "Network rules should allow UDP"
  }
}

