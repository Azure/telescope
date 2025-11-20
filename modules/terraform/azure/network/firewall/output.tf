output "firewall_id" {
  description = "ID of the Azure Firewall"
  value       = azurerm_firewall.firewall.id
}

output "firewall_private_ip" {
  description = "Private IP address of the Azure Firewall"
  value       = azurerm_firewall.firewall.ip_configuration[0].private_ip_address
}

output "firewall_name" {
  description = "Name of the Azure Firewall"
  value       = azurerm_firewall.firewall.name
}
