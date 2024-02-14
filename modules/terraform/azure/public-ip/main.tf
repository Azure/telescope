locals {
  public_ip_config_map = { for ip in var.public_ip_config_list : ip.name => ip }
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
