resource "azurerm_firewall" "firewall" {
  name                = var.firewall_config.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = var.firewall_config.sku_name
  sku_tier            = var.firewall_config.sku_tier
  firewall_policy_id  = var.firewall_config.firewall_policy_id
  threat_intel_mode   = var.firewall_config.threat_intel_mode
  tags                = var.tags

  dynamic "dns" {
    for_each = var.firewall_config.dns_proxy_enabled ? [1] : []
    content {
      servers       = var.firewall_config.dns_servers
      enable_proxy  = true
    }
  }

  ip_configuration {
    name                 = var.firewall_config.ip_configuration_name
    subnet_id            = var.firewall_config.subnet_id
    public_ip_address_id = var.firewall_config.public_ip_address_id
  }
}

resource "azurerm_firewall_nat_rule_collection" "nat_rules" {
  for_each = {
    for collection in coalesce(var.firewall_config.nat_rule_collections, []) :
    collection.name => collection
  }

  name                = each.value.name
  azure_firewall_name = azurerm_firewall.firewall.name
  resource_group_name = var.resource_group_name
  priority            = each.value.priority
  action              = each.value.action

  dynamic "rule" {
    for_each = each.value.rules
    content {
      name                  = rule.value.name
      source_addresses      = lookup(rule.value, "source_addresses", null)
      source_ip_groups      = lookup(rule.value, "source_ip_groups", null)
      destination_ports     = rule.value.destination_ports
      destination_addresses = rule.value.destination_addresses
      translated_address    = rule.value.translated_address
      translated_port       = rule.value.translated_port
      protocols             = rule.value.protocols
    }
  }
}

resource "azurerm_firewall_network_rule_collection" "network_rules" {
  for_each = {
    for collection in coalesce(var.firewall_config.network_rule_collections, []) :
    collection.name => collection
  }

  name                = each.value.name
  azure_firewall_name = azurerm_firewall.firewall.name
  resource_group_name = var.resource_group_name
  priority            = each.value.priority
  action              = each.value.action

  dynamic "rule" {
    for_each = each.value.rules
    content {
      name                  = rule.value.name
      source_addresses      = lookup(rule.value, "source_addresses", null)
      source_ip_groups      = lookup(rule.value, "source_ip_groups", null)
      destination_ports     = rule.value.destination_ports
      destination_addresses = lookup(rule.value, "destination_addresses", null)
      destination_fqdns     = lookup(rule.value, "destination_fqdns", null)
      destination_ip_groups = lookup(rule.value, "destination_ip_groups", null)
      protocols             = rule.value.protocols
    }
  }
}

resource "azurerm_firewall_application_rule_collection" "application_rules" {
  for_each = {
    for collection in coalesce(var.firewall_config.application_rule_collections, []) :
    collection.name => collection
  }

  name                = each.value.name
  azure_firewall_name = azurerm_firewall.firewall.name
  resource_group_name = var.resource_group_name
  priority            = each.value.priority
  action              = each.value.action

  dynamic "rule" {
    for_each = each.value.rules
    content {
      name             = rule.value.name
      source_addresses = lookup(rule.value, "source_addresses", null)
      source_ip_groups = lookup(rule.value, "source_ip_groups", null)
      target_fqdns     = lookup(rule.value, "target_fqdns", null)
      fqdn_tags        = lookup(rule.value, "fqdn_tags", null)

      dynamic "protocol" {
        for_each = lookup(rule.value, "protocols", [])
        content {
          port = protocol.value.port
          type = protocol.value.type
        }
      }
    }
  }
}
