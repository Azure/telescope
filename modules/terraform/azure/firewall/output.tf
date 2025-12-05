output "firewall_private_ips" {
  description = "Map of firewall names to their private IP addresses"
  value = {
    for fw_name, fw in azurerm_firewall.firewall : fw.name => fw.ip_configuration[0].private_ip_address
  }
  
  depends_on = [
    azurerm_firewall_nat_rule_collection.nat_rules,
    azurerm_firewall_network_rule_collection.network_rules,
    azurerm_firewall_application_rule_collection.application_rules
  ]

  # Ensure all firewalls have assigned private IPs
  precondition {
    condition = alltrue([
      for fw_name, fw in azurerm_firewall.firewall : 
      fw.ip_configuration[0].private_ip_address != null && fw.ip_configuration[0].private_ip_address != ""
    ])
    error_message = "One or more firewalls do not have assigned private IP addresses. Firewall details: ${jsonencode({ for fw_name, fw in azurerm_firewall.firewall : fw_name => fw.ip_configuration[0].private_ip_address })}"
  }
}
