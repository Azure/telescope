output "private_ip_address" {
  description = "Private IP address of the firewall"
  value       = azurerm_firewall.firewall.ip_configuration[0].private_ip_address
}