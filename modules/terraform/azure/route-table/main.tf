resource "azurerm_route_table" "route_table" {
  name                          = var.route_table_config.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  bgp_route_propagation_enabled = var.route_table_config.bgp_route_propagation_enabled
  tags                          = var.tags
}

resource "azurerm_route" "routes" {
  for_each = { for route in var.route_table_config.routes : route.name => route }

  name                = each.value.name
  resource_group_name = var.resource_group_name
  route_table_name    = azurerm_route_table.route_table.name
  address_prefix = (
    each.value.address_prefix_publicip_name != null
    ? "${var.public_ip_addresses[each.value.address_prefix_publicip_name]}/32"
    : each.value.address_prefix
  )
  next_hop_type = each.value.next_hop_type
  next_hop_in_ip_address = (
    each.value.next_hop_firewall_name != null
    ? try(var.firewall_private_ips[each.value.next_hop_firewall_name], null)
    : each.value.next_hop_in_ip_address
  )

  lifecycle {
    precondition {
      condition = (each.value.next_hop_type != "VirtualAppliance" ||
        each.value.next_hop_firewall_name == null ||
        (try(var.firewall_private_ips[each.value.next_hop_firewall_name], null) != null))
      error_message = "Route '${each.value.name}': Firewall '${coalesce(each.value.next_hop_firewall_name, "UNKNOWN")}' not found! Available firewalls: ${jsonencode(keys(var.firewall_private_ips))}. Firewall IPs: ${jsonencode(var.firewall_private_ips)}"
    }
  }
}

resource "azurerm_subnet_route_table_association" "subnet_associations" {
  for_each = { for assoc in var.route_table_config.subnet_associations : assoc.subnet_name => assoc }

  subnet_id      = var.subnets_ids[each.value.subnet_name]
  route_table_id = azurerm_route_table.route_table.id

  depends_on = [azurerm_route.routes]
}
