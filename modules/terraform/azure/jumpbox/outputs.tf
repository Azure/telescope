output "connection_info" {
  description = "Jumpbox connection details"
  value = {
    public_ip = azurerm_public_ip.jumpbox.ip_address
    username  = local.admin_username
    name      = var.name
  }
}