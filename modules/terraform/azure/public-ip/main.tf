locals {
  expanded_public_ip_config_list = flatten([
    for ip in var.public_ip_config_list : [
      for i in range(var.pip_count_override > 0 ? var.pip_count_override : ip.count) : {
        name              = (var.pip_count_override > 0 ? var.pip_count_override : ip.count) > 1 ? "${ip.name}-${i + 1}" : ip.name
        zones             = ip.zones
        allocation_method = ip.allocation_method
        sku               = ip.sku
      }
    ]
  ])

  public_ip_config_map = { for ip in local.expanded_public_ip_config_list : ip.name => ip }
}

resource "azurerm_public_ip" "pip" {
  for_each = local.public_ip_config_map

  name                = each.value.name
  location            = var.location
  zones               = each.value.zones
  resource_group_name = var.resource_group_name
  allocation_method   = each.value.allocation_method
  sku                 = each.value.sku
  tags                = var.tags
}
