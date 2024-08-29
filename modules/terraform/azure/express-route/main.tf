resource "azurerm_virtual_network_gateway" "vnet_gateway" {
  name                = var.vnet_gateway_config.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.vnet_gateway_config.sku
  type                = var.vnet_gateway_config.type
  vpn_type            = var.vnet_gateway_config.vpn_type
  ip_configuration {
    name                          = var.vnet_gateway_config.ip_configuration.name
    public_ip_address_id          = var.vnet_gateway_config.ip_configuration.public_ip_address_id
    private_ip_address_allocation = var.vnet_gateway_config.ip_configuration.private_ip_address_allocation
    subnet_id                     = var.vnet_gateway_config.ip_configuration.subnet_id
  }
  tags = var.tags
}

resource "azurerm_virtual_network_gateway_connection" "onpremise" {
  name                = var.vnet_gateway_connection_config.connection_name
  location            = var.location
  resource_group_name = var.resource_group_name
  depends_on          = [azurerm_virtual_network_gateway.vnet_gateway]

  type                       = var.vnet_gateway_connection_config.type
  virtual_network_gateway_id = azurerm_virtual_network_gateway.vnet_gateway.id

  tags = var.tags
}
