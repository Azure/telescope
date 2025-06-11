output "dns_zone_ids" {
  description = "Map of DNS zone names to their resource IDs"
  value       = { for name, zone in azurerm_dns_zone.dns_zones : name => zone.id }
}
