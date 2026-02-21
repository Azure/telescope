output "network_security_group_name" {
  value = try(azurerm_network_security_group.nsg[0].name, "")
}

output "nics" {
  description = "Map of the nics"
  value       = { for nic in azurerm_network_interface.nic : nic.name => nic.id }
}

output "subnets" {
  description = "Map of subnet names to subnet objects"
  value       = { for name, subnet in azurerm_subnet.subnet : name => subnet.id }
}

output "vnet_id" {
  description = "vnet id"
  value       = azurerm_virtual_network.vnet.id
}
