resource "azurerm_express_route_circuit" "express_route" {
  name                  = var.name
  resource_group_name   = var.resource_group_name
  location              = var.location
  tags                  = var.tags
  service_provider_name = var.service_provider_name
  peering_location      = var.peering_location
  bandwidth_in_mbps     = var.bandwidth_in_mbps

  sku {
    tier   = "Standard"
    family = "MeteredData"
  }
}

resource "azurerm_virtual_network_gateway" {
    
}

resource "azurerm_virtual_network_gateway_connection" {
    
}