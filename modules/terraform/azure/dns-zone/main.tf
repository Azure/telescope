local {
  dns_zones = { for zone in var.dns_zones : zone.name => zone }
}

resource "azurerm_dns_zone" "dns_zones" {
  for_each            = local.dns_zones
  name                = each.key
  resource_group_name = var.resource_group_name
  tags                = var.tags
}
