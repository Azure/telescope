output "firewall_private_ips" {
  description = "Map of firewall names to their private IP addresses"
  value       = { for fw in azurerm_firewall.firewall : fw.name => fw.ip_configuration[0].private_ip_address }
}
