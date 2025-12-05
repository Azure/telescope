output "firewall_private_ips_map" {
  description = "Map of firewall name to private IP address"
  value = {
    (azurerm_firewall.firewall.name) = one([for config in azurerm_firewall.firewall.ip_configuration : config.private_ip_address])
  }
}
