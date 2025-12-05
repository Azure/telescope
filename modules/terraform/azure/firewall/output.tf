output "firewall_private_ips_map" {
  description = "Map of firewall name to private IP address"
  value = {
    (azurerm_firewall.firewall.name) = azurerm_firewall.firewall.ip_configuration[0].private_ip_address
  }
}
