resource "aws_vpc_endpoint" "vpc_endpoint" {
  vpc_id             = var.vpc_id
  service_name       = var.pe_config.pe_service_name
  vpc_endpoint_type  = var.pe_config.vpc_endpoint_type
  subnet_ids         = var.pe_config.subnet_ids
  security_group_ids = var.pe_config.security_group_ids
  route_table_ids    = var.pe_config.route_table_ids

  tags = var.tags
}