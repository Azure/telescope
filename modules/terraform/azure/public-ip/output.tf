output "pip_ids" {
  value = { for ip in azurerm_public_ip.pip : ip.name => ip.id }
}

output "pip_addresses" {
  description = "Map of public IP names to their IP addresses"
  value       = { for ip in azurerm_public_ip.pip : ip.name => ip.ip_address }
}
