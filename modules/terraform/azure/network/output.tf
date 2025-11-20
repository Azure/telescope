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

output "firewalls" {
  description = "Map of firewall names to their properties"
  value = {
    for fw_name, fw_config in local.firewalls_map :
    fw_name => {
      id         = module.firewall[fw_name].firewall.id
      private_ip = module.firewall[fw_name].firewall.ip_configuration[0].private_ip_address
      name       = module.firewall[fw_name].firewall.name
    }
  }
}
