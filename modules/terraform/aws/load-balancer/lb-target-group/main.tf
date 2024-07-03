locals {
  lb_listener_map             = { for lb_listener in var.lb_tg_config.lb_listener : "${lb_listener.port}-${lb_listener.protocol}" => lb_listener }
  target_group_attachment_map = { for target_group_attachment in var.lb_tg_config.lb_target_group_attachment : "${target_group_attachment.vm_name}-${target_group_attachment.port}" => target_group_attachment }
  all_vms                     = { for vm in data.aws_instance.vm_instance : vm.tags.Name => vm... }
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
  for_each = local.target_group_attachment_map
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [each.value.vm_name]
  }

  filter {
    name   = "instance-state-name"
    values = ["running"]
  }
}

data "aws_acm_certificate" "telescope_cert" {
  count    = var.lb_tg_config.certificate_domain_name != null ? 1 : 0
  domain   = var.lb_tg_config.certificate_domain_name
  statuses = ["ISSUED"]
}

resource "aws_lb_target_group" "target_group" {
  port     = var.lb_tg_config.port
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
    "Name" = "${var.lb_tg_config.role}-${var.lb_tg_config.tg_suffix}-${var.lb_tg_config.protocol}-${var.lb_tg_config.port}"
  })
}

resource "aws_lb_listener" "nlb_listener" {
  for_each = local.lb_listener_map

  load_balancer_arn = var.load_balancer_arn
  port              = each.value.port
  protocol          = each.value.protocol
  certificate_arn   = each.value.protocol == "HTTPS" ? data.aws_acm_certificate.telescope_cert[0].arn : ""

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.target_group.arn
  }
  depends_on = [aws_lb_target_group.target_group]

  tags = var.tags
}

resource "aws_lb_target_group_attachment" "nlb_target_group_attachment" {
  for_each = local.target_group_attachment_map

  target_group_arn = aws_lb_target_group.target_group.arn
  target_id        = local.all_vms[each.value.vm_name][0].id
  port             = each.value.port
}
