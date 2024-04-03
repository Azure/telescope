output "vpc" {
  description = "Vpc information"
  value       = aws_vpc.vpc
}

output "route_tables" {
  description = "Route tables associated with vpc"
  value = list(aws_vpc.route_tables)
}