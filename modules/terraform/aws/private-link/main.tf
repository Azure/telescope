
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

# Endpoint Service  
resource "aws_vpc_endpoint_service" "server_service" {
  acceptance_required        = false
  network_load_balancer_arns = [var.service_lb_arn]

  tags = var.tags
}

# Interface Endpoint
module "privateendpoint" {
  source = "../vpc-endpoint"

  pe_config = {
    pe_vpc_name  = var.client_vpc_name
    service_name = aws_vpc_endpoint_service.server_service.service_name
  }

  vpc_endpoint_type  = "Interface"
  subnet_ids         = [data.aws_subnet.client_subnet.id]
  security_group_ids = [data.aws_security_group.security_group.id]

  tags = var.tags
}

