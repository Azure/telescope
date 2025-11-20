output "network_security_group_name" {
  value = try(azurerm_network_security_group.nsg[0].name, "")
}

output "nics" {
  description = "Map of the nics"
  value       = { for nic in azurerm_network_interface.nic : nic.name => nic.id }
}

output "subnets" {
  description = "Map of subnet names to subnet objects"
  value = {
    for subnet_id in azurerm_virtual_network.vnet.subnet[*].id :
    split("/", subnet_id)[length(split("/", subnet_id)) - 1] => subnet_id
  }
}

output "vnet_id" {
  description = "vnet id"
  value       = azurerm_virtual_network.vnet.id
}

output "route_tables" {
  description = "Map of route table names to their associated subnets"
  value = {
    for rt_name, rt_module in module.route_table :
    rt_name => keys(rt_module.subnet_associations)
  }
}
