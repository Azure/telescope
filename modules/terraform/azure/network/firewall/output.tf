output "private_ip_address" {
  description = "Private IP address of the firewall"
  value       = azurerm_firewall.firewall.ip_configuration[0].private_ip_address
  depends_on = [
    azurerm_firewall_nat_rule_collection.nat_rules,
    azurerm_firewall_network_rule_collection.network_rules,
    azurerm_firewall_application_rule_collection.application_rules
  ]
}
