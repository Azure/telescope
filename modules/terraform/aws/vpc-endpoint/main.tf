# aws vpc private endpoint 

resource "aws_vpc_endpoint" "client_endpoint" {
  vpc_id            = data.aws_vpc.client.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  subnet_ids         = [data.aws_subnet.client_subnet.id]
  security_group_ids = [data.aws_security_group.security_group.id]
  route_table_ids   = [aws_route_table.main.id]

  tags = var.tags
}
