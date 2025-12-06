locals {
  # Resolve subnet_id and public_ip_address_id for each firewall config
  resolved_firewall_config_map = {
    for fw in var.firewall_config_list : fw.name => merge(fw, {
      subnet_id = fw.subnet_id != null ? fw.subnet_id : (
        fw.subnet_name != null ? try(var.subnets_map[fw.subnet_name], null) : null
      )
      public_ip_address_id = fw.public_ip_address_id != null ? fw.public_ip_address_id : (
        fw.public_ip_name != null ? try(var.public_ips_map[fw.public_ip_name], null) : null
      )
    })
  }

  firewall_config_map = local.resolved_firewall_config_map
}

resource "azurerm_firewall" "firewall" {
  for_each = local.firewall_config_map

  name                = each.value.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = each.value.sku_name
  sku_tier            = each.value.sku_tier
  firewall_policy_id  = each.value.firewall_policy_id
  threat_intel_mode   = each.value.threat_intel_mode
  dns_servers         = each.value.dns_proxy_enabled ? each.value.dns_servers : null
  dns_proxy_enabled   = each.value.dns_proxy_enabled
  tags                = var.tags

  ip_configuration {
    name                 = each.value.ip_configuration_name
    subnet_id            = each.value.subnet_id
    public_ip_address_id = each.value.public_ip_address_id
  }

}

resource "azurerm_firewall_nat_rule_collection" "nat_rules" {
  for_each = {
    for item in flatten([
      for fw_name, fw_config in local.firewall_config_map : [
        for collection in coalesce(fw_config.nat_rule_collections, []) : {
          fw_name     = fw_name
          fw_name_col = "${fw_name}-${collection.name}"
          collection  = collection
        }
      ]
    ]) : item.fw_name_col => item
  }

  name                = each.value.collection.name
  azure_firewall_name = azurerm_firewall.firewall[each.value.fw_name].name
  resource_group_name = var.resource_group_name
  priority            = each.value.collection.priority
  action              = each.value.collection.action

  dynamic "rule" {
    for_each = each.value.collection.rules
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
    for item in flatten([
      for fw_name, fw_config in local.firewall_config_map : [
        for collection in coalesce(fw_config.network_rule_collections, []) : {
          fw_name     = fw_name
          fw_name_col = "${fw_name}-${collection.name}"
          collection  = collection
        }
      ]
    ]) : item.fw_name_col => item
  }

  name                = each.value.collection.name
  azure_firewall_name = azurerm_firewall.firewall[each.value.fw_name].name
  resource_group_name = var.resource_group_name
  priority            = each.value.collection.priority
  action              = each.value.collection.action

  dynamic "rule" {
    for_each = each.value.collection.rules
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
    for item in flatten([
      for fw_name, fw_config in local.firewall_config_map : [
        for collection in coalesce(fw_config.application_rule_collections, []) : {
          fw_name     = fw_name
          fw_name_col = "${fw_name}-${collection.name}"
          collection  = collection
        }
      ]
    ]) : item.fw_name_col => item
  }

  name                = each.value.collection.name
  azure_firewall_name = azurerm_firewall.firewall[each.value.fw_name].name
  resource_group_name = var.resource_group_name
  priority            = each.value.collection.priority
  action              = each.value.collection.action

  dynamic "rule" {
    for_each = each.value.collection.rules
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
