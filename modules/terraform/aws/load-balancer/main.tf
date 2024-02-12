locals {
  role            = var.loadbalancer_config.role
  lb_target_group = var.loadbalancer_config.lb_target_group
  lb_target_group_map = {
    for tg in local.lb_target_group :
    "${tg.vpc_name}-${tg.tg_suffix}" => tg
  }
}

data "aws_subnet" "subnet" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${var.loadbalancer_config.subnet_name}"]
  }
}

resource "aws_lb" "nlb" {
  internal           = true
  load_balancer_type = var.loadbalancer_config.load_balancer_type
  subnets            = [data.aws_subnet.subnet.id]

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
}
