resource "azurerm_nat_gateway" "nat_gateway" {
  name                = var.nat_gateway_name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = "Standard"

  tags = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "nat_gateway_ip_association" {
  count = length(var.nat_gateway_association.public_ip_names)

  nat_gateway_id       = azurerm_nat_gateway.nat_gateway.id
  public_ip_address_id = var.public_ips[var.nat_gateway_association.public_ip_names[count.index]].id
}

resource "azurerm_subnet_nat_gateway_association" "nat_gateway_subnet_association" {
  count = length(var.nat_gateway_association.subnet_names)

  subnet_id      = var.subnets_map[var.nat_gateway_association.subnet_names[count.index]].id
  nat_gateway_id = azurerm_nat_gateway.nat_gateway.id
}
