output "subnet_associations" {
  description = "List of associated subnet names"
  value       = keys(azurerm_subnet_route_table_association.subnet_associations)
}

