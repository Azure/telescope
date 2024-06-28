locals {
  lb_listener_map             = { for lb_listener in var.lb_tg_config.lb_listener : "${lb_listener.port}-${lb_listener.protocol}" => lb_listener }
  target_group_attachment_map = { for target_group_attachment in var.lb_tg_config.lb_target_group_attachment : "${target_group_attachment.vm_name}-${target_group_attachment.port}" => target_group_attachment }
}

data "aws_vpc" "vpc" {
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [var.lb_tg_config.vpc_name]
  }
}

data "aws_instance" "vm_instance" {
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [local.target_group_attachment_map[0].vm_name]
  }

  filter {
    name   = "instance-state-name"
    values = ["running"]
  }
}

resource "aws_lb_target_group" "target_group" {
  count = var.lb_tg_config.rule_count

  port     = var.lb_tg_config.rule_count > 1 ? var.lb_tg_config.port + count.index + 1 : var.lb_tg_config.port
  protocol = var.lb_tg_config.protocol
  vpc_id   = data.aws_vpc.vpc.id

  health_check {
    port                = var.lb_tg_config.health_check.port
    protocol            = var.lb_tg_config.health_check.protocol
    interval            = var.lb_tg_config.health_check.interval
    timeout             = var.lb_tg_config.health_check.timeout
    healthy_threshold   = var.lb_tg_config.health_check.healthy_threshold
    unhealthy_threshold = var.lb_tg_config.health_check.unhealthy_threshold
  }

  tags = merge(var.tags, {
    "Name" = var.lb_tg_config.rule_count > 1 ? "${var.lb_tg_config.role}-${var.lb_tg_config.tg_suffix}-${count.index + 1}" : "${var.lb_tg_config.role}-${var.lb_tg_config.tg_suffix}"
  })
}

resource "aws_lb_listener" "nlb_listener" {
  for_each = local.lb_listener_map

  load_balancer_arn = var.load_balancer_arn
  port              = var.lb_tg_config.rule_count > 1 ? each.value.port + count.index + 1 : each.value.port
  protocol          = each.value.protocol
  certificate_arn   = each.value.protocol == "HTTPS" ? "arn:aws:acm:us-east-2:891516228446:certificate/df5291b7-c950-4fa2-b7b9-971a796030ea" : ""

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.target_group[count.index].arn
  }

  tags = var.tags
}

resource "aws_lb_target_group_attachment" "nlb_target_group_attachment" {
  for_each = local.target_group_attachment_map

  target_group_arn = aws_lb_target_group.target_group[count.index].arn
  target_id        = data.aws_instance.vm_instance.id
  port             = each.value.port
}
