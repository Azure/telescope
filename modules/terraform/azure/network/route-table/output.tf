output "route_table_id" {
  description = "The ID of the route table"
  value       = azurerm_route_table.route_table.id
}

output "route_table_name" {
  description = "The name of the route table"
  value       = azurerm_route_table.route_table.name
}
