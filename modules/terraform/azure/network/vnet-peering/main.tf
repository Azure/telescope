data "azurerm_virtual_network" "client_vnet" {
  name                = "client-vnet"
  resource_group_name = var.resource_group_name
}

output "client_vnet_id" {
  value = data.azurerm_virtual_network.client_vnet.id
}

output "client_vnet_name" {
  value = data.azurerm_virtual_network.client_vnet.name
}

data "azurerm_virtual_network" "server_vnet" {
  name                = "server-vnet"
  resource_group_name = var.resource_group_name
}

output "server_vnet_id" {
  value = data.azurerm_virtual_network.server_vnet.id
}

output "server_vnet_name" {
  value = data.azurerm_virtual_network.server_vnet.name
}

resource "azurerm_virtual_network_peering" "to_client" {
  name                         = "servertoclient"
  resource_group_name          = var.resource_group_name
  virtual_network_name         = data.azurerm_virtual_network.server_vnet.name
  remote_virtual_network_id    = data.azurerm_virtual_network.client_vnet.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}

resource "azurerm_virtual_network_peering" "to_server" {
  name                         = "clienttoserver"
  resource_group_name          = var.resource_group_name
  virtual_network_name         = data.azurerm_virtual_network.client_vnet.name
  remote_virtual_network_id    = data.azurerm_virtual_network.server_vnet.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}
