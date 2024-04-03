output "vpc" {
  description = "Vpc information"
  value       = aws_vpc.vpc
}

output "route_tables" {
  description = "Route tables associated with vpc"
  value = { for route_table in aws_route_table.route_tables: route_table.tags.Name => route_table.id }
}