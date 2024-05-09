locals {
  ingress_sg_rules_map = var.sg_rules == null ? {} : { for idx, rule in var.sg_rules.ingress : idx => rule }
  egress_sg_rules_map  = var.sg_rules == null ? {} : { for idx, rule in var.sg_rules.egress : idx => rule }
}

resource "aws_security_group" "security_group" {
  dynamic "ingress" {
    for_each = local.ingress_sg_rules_map
    content {
      from_port   = ingress.value.from_port
      to_port     = ingress.value.to_port
      protocol    = ingress.value.protocol
      cidr_blocks = [ingress.value.cidr_block]
    }
  }

  dynamic "egress" {
    for_each = local.egress_sg_rules_map
    content {
      from_port   = egress.value.from_port
      to_port     = egress.value.to_port
      protocol    = egress.value.protocol
      cidr_blocks = [egress.value.cidr_block]
    }
  }

  vpc_id = var.vpc.id
  tags   = var.tags
}