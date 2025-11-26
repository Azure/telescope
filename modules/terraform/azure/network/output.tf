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

output "firewalls" {
  description = "Map of firewall names to their private IPs"
  value = {
    for fw_name, fw in module.firewall :
    fw_name => {
      private_ip = fw.private_ip_address
    }
  }
}
