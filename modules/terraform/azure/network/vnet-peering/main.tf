data "azurerm_virtual_network" "client_vnet"{
    name = "client_vnet"
    resource_group_name = var.resource_group_name
}

output "client_vnet" {
    value = data.azurerm_virtual_network.client_vnet
}

data "azurerm_virtual_network" "server_vnet"{
    name = "server_vnet"
    resource_group_name = var.resource_group_name
}

output "server_vnet" {
    value = data.azurerm_virtual_network.server_vnet
}

resource "azurerm_virtual_network_peering" "to_client" {
    name = "servertoclient"
    resource_group_name = var.resource_group_name
    virtual_network_name = server_vnet.name
    remote_virtual_network_id = client_vnet.id
}

resource "azurerm_virtual_network_peering" "to_server" {
    name = "clienttoserver"
    resource_group_name = var.resource_group_name
    virtual_network_name = client_vnet.name
    remote_virtual_network_id = server_vnet.id
}