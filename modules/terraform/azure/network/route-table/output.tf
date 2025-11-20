output "subnet_associations" {
  description = "Map of subnet names to route table association IDs"
  value = {
    for subnet_name, assoc in azurerm_subnet_route_table_association.subnet_associations :
    subnet_name => assoc.id
  }
}
