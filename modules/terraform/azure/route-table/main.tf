locals {
  # Expand routes that reference a public IP prefix into multiple routes
  # when multiple public IPs match that prefix (e.g., "firewall-pip" matches "firewall-pip-1", "firewall-pip-2", etc.)
  expanded_routes = flatten([
    for route in var.route_table_config.routes : (
      route.address_prefix_publicip_name != null
      ? [
        # Find all public IPs matching: exact name OR prefixed with "{name}-"
        for pip_name, pip in var.public_ips : merge(route, {
          name                         = length([for k, _ in var.public_ips : k if k == route.address_prefix_publicip_name || startswith(k, "${route.address_prefix_publicip_name}-")]) > 1 ? "${route.name}-${pip_name}" : route.name
          address_prefix               = "${pip.ip_address}/32"
          address_prefix_publicip_name = null
        }) if pip_name == route.address_prefix_publicip_name || startswith(pip_name, "${route.address_prefix_publicip_name}-")
      ]
      : [route]
    )
  ])
}

resource "azurerm_route_table" "route_table" {
  name                          = var.route_table_config.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  bgp_route_propagation_enabled = var.route_table_config.bgp_route_propagation_enabled
  tags                          = var.tags
}

resource "azurerm_route" "routes" {
  for_each = { for route in local.expanded_routes : route.name => route }

  name                = each.value.name
  resource_group_name = var.resource_group_name
  route_table_name    = azurerm_route_table.route_table.name
  address_prefix      = each.value.address_prefix
  next_hop_type       = each.value.next_hop_type
  next_hop_in_ip_address = (
    each.value.next_hop_firewall_name != null
    ? try(var.firewall_private_ips[each.value.next_hop_firewall_name], null)
    : each.value.next_hop_in_ip_address
  )

}

resource "azurerm_subnet_route_table_association" "subnet_associations" {
  for_each = { for assoc in var.route_table_config.subnet_associations : assoc.subnet_name => assoc }

  subnet_id      = var.subnets_ids[each.value.subnet_name]
  route_table_id = azurerm_route_table.route_table.id
  depends_on     = [azurerm_route.routes]
}
