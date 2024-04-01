# aws vpc private endpoint 

data "aws_vpc" "client_vpc" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${var.client_vpc_name}"]
  }
}

data "aws_subnet" "client_subnet" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${var.client_subnet_name}"]
  }
}

data "aws_security_group" "security_group" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${var.client_security_group_name}"]
  }
}

resource "aws_vpc_endpoint" "client_endpoint" {
  vpc_id            = data.aws_vpc.client.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  subnet_ids         = [data.aws_subnet.client_subnet.id]
  security_group_ids = [data.aws_security_group.security_group.id]

  tags = var.tags
}
