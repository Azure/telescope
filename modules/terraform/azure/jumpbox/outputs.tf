output "public_ip" {
  description = "Public IP address of the jumpbox"
  value       = azurerm_public_ip.jumpbox.ip_address
}

output "private_ip" {
  description = "Private IP address of the jumpbox"
  value       = azurerm_network_interface.jumpbox.private_ip_address
}

output "admin_username" {
  description = "Admin username configured on the jumpbox"
  value       = local.admin_username
}

output "name" {
  description = "Jumpbox VM name"
  value       = var.name
}

output "network_interface_id" {
  description = "Network interface resource ID"
  value       = azurerm_network_interface.jumpbox.id
}