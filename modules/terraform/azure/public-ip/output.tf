output "public_ips" {
  description = "Map of public IP names to their objects containing id and ip_address"
  value = {
    for ip in azurerm_public_ip.pip : ip.name => {
      id         = ip.id
      ip_address = ip.ip_address
    }
  }
}
