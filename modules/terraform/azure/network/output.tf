output "network_security_group_name" {
  value = azurerm_network_security_group.nsg.name
}

output "nics" {
  description = "Map of the nics"
  value       = { for nic in azurerm_network_interface.nic : nic.name => nic.id }
}

output "subnets" {
  description = "Map of subnet names to subnet objects"
  value       = { for subnet in azurerm_subnet.subnets : subnet.name => subnet.id }
}
