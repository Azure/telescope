locals {
  role            = var.loadbalancer_config.role
  lb_target_group = var.loadbalancer_config.lb_target_group
  lb_target_group_map = {
    for tg in local.lb_target_group :
    "${tg.vpc_name}-${tg.tg_suffix}" => tg
  }
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

data "aws_security_group" "lb_security_group" {
  count = var.loadbalancer_config.security_group_name != null ? 1 : 0
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [var.loadbalancer_config.security_group_name]
  }
}

resource "aws_lb" "nlb" {
  internal           = var.loadbalancer_config.is_internal_lb
  load_balancer_type = var.loadbalancer_config.load_balancer_type
  subnets            = values(data.aws_subnet.subnets)[*].id
  security_groups    = var.loadbalancer_config.security_group_name != null ? [data.aws_security_group.lb_security_group[0].id] : []

  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
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
  depends_on = [aws_lb.nlb]
}
