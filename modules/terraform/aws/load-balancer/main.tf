locals {
  role            = var.loadbalancer_config.role
  lb_target_group = var.loadbalancer_config.lb_target_group
  lb_target_group_map = {
    for tg in local.lb_target_group :
    "${tg.vpc_name}-${tg.tg_suffix}" => tg
  }
  lb_vpc_name = var.loadbalancer_config.vpc_name
}

data "aws_subnet" "subnets" {
  for_each = { for subnet_name in var.loadbalancer_config.subnet_names : subnet_name => subnet_name }

  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [each.value]
  }
}

data "aws_vpc" "server_vpc" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${local.lb_vpc_name}"]
  }
}

resource "aws_lb" "nlb" {
  internal           = var.loadbalancer_config.is_internal_lb
  load_balancer_type = var.loadbalancer_config.load_balancer_type
  subnets            = values(data.aws_subnet.subnets)[*].id
  security_groups    = var.loadbalancer_config.load_balancer_type == "application" ? [aws_security_group.alb_security_group.id] : []
  
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
}

resource "aws_security_group" "alb_security_group" {
  name = "applbrules"
  description = "Allow inbound HTTP and HTTPS" 
  vpc_id = data.aws_vpc.server_vpc.id
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
}

resource "aws_vpc_security_group_ingress_rule" "allow_inbound_http" {
  security_group_id = aws_security_group.alb_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp" 
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "allow_inbound_https" {
  security_group_id = aws_security_group.alb_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp" 
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "allow_outbound_http" {
  security_group_id = aws_security_group.alb_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp" 
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "allow_outbound_https" {
  security_group_id = aws_security_group.alb_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp" 
  from_port         = 443
  to_port           = 443
}

module "lb_target_group" {
  source   = "./lb-target-group"
  for_each = local.lb_target_group_map

  lb_tg_config      = each.value
  load_balancer_arn = aws_lb.nlb.arn
  run_id            = var.run_id
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
}
