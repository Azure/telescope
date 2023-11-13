output "pip_ids" {
  value = { for ip in azurerm_public_ip.pip : ip.name => ip.id }
}
