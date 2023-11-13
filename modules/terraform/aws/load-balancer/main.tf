locals {
  name_prefix     = var.loadbalancer_config.name_prefix
  lb_target_group = var.loadbalancer_config.lb_target_group
  lb_target_group_map = {
    for tg in local.lb_target_group :
    "${tg.vpc_name}-${tg.tg_suffix}" => tg
  }
}

data "aws_subnet" "subnet" {
  filter {
    name   = "tag:Name"
    values = ["${var.loadbalancer_config.subnet_name}-${var.job_id}"]
  }
}

resource "aws_lb" "nlb" {
  name               = "${local.name_prefix}-${var.job_id}"
  internal           = false
  load_balancer_type = var.loadbalancer_config.load_balancer_type
  subnets            = [data.aws_subnet.subnet.id]

  tags = var.tags
}

module "lb_target_group" {
  source   = "./lb-target-group"
  for_each = local.lb_target_group_map

  lb_tg_config      = each.value
  load_balancer_arn = aws_lb.nlb.arn
  job_id            = var.job_id
  tags              = var.tags
}
