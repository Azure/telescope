data "aws_vpc" "vpc" {
  filter {
    name   = "tag:Name"
    values = ["${var.lb_tg_config.vpc_name}-${var.job_id}"]
  }
}

data "aws_instance" "vm_instance" {
  filter {
    name   = "tag:Name"
    values = ["${var.lb_tg_config.lb_target_group_attachment.vm_name}-${var.job_id}"]
  }
}

resource "aws_lb_target_group" "target_group" {
  count = var.lb_tg_config.rule_count

  name     =  var.lb_tg_config.rule_count > 1 ? "${var.lb_tg_config.name_prefix}-${var.job_id}-${var.lb_tg_config.tg_suffix}-${count.index + 1}" : "${var.lb_tg_config.name_prefix}-${var.job_id}-${var.lb_tg_config.tg_suffix}"
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

  tags = var.tags
}

resource "aws_lb_listener" "nlb_listener" {
  count = var.lb_tg_config.rule_count

  load_balancer_arn = var.load_balancer_arn
  port              = var.lb_tg_config.rule_count > 1 ? var.lb_tg_config.lb_listener.port + count.index + 1 : var.lb_tg_config.lb_listener.port
  protocol          = var.lb_tg_config.lb_listener.protocol

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.target_group[count.index].arn
  }

  tags = var.tags
}

resource "aws_lb_target_group_attachment" "nlb_target_group_attachment" {
  count = var.lb_tg_config.rule_count

  target_group_arn = aws_lb_target_group.target_group[count.index].arn
  target_id        = data.aws_instance.vm_instance.id
  port             = var.lb_tg_config.lb_target_group_attachment.port
}
