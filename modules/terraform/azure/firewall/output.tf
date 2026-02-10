output "firewall_private_ips" {
  description = "Map of firewall names to their private IP addresses"
  value       = { for fw in azurerm_firewall.firewall : fw.name => fw.ip_configuration[0].private_ip_address }
}

output "firewall_public_ips" {
  description = "Map of firewall names to their list of public IP addresses"
  value = {
    for fw in azurerm_firewall.firewall : fw.name => [
      for ip_config in fw.ip_configuration : ip_config.public_ip_address_id
    ]
  }
}
