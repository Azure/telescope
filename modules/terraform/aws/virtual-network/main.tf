locals {
  ingress_sg_rules_map = { for idx, rule in var.network_config.sg_rules.ingress : idx => rule }
  egress_sg_rules_map  = { for idx, rule in var.network_config.sg_rules.egress : idx => rule }
  vpc_name             = var.network_config.vpc_name
  subnet_map           = { for subnet in var.network_config.subnet : subnet.name => subnet }
  security_group_name  = var.network_config.security_group_name
  tags                 = merge(var.tags, { "role" = var.network_config.role })
}

resource "aws_vpc" "vpc" {
  cidr_block = var.network_config.vpc_cidr_block

  tags = merge(local.tags, {
    "Name" = local.vpc_name
  })
}

resource "aws_subnet" "subnets" {
  for_each = local.subnet_map

  vpc_id     = aws_vpc.vpc.id
  cidr_block = each.value.cidr_block

  availability_zone = each.value.zone == null ? var.zone : each.value.zone

  tags = merge(local.tags, {
    "Name" = each.value.name
  })
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

  vpc_id = aws_vpc.vpc.id

  tags = merge(local.tags, {
    "Name" = local.security_group_name
  })
}

resource "aws_internet_gateway" "internet_gateway" {
  vpc_id = aws_vpc.vpc.id

  tags = merge(local.tags, {
    "Name" = "${local.vpc_name}-igw"
  })
}

resource "aws_route_table" "route_table" {
  vpc_id = aws_vpc.vpc.id

  route {
    cidr_block = var.network_config.route_table_cidr_block
    gateway_id = aws_internet_gateway.internet_gateway.id
  }

  tags = merge(local.tags, {
    "Name" = "${local.vpc_name}-rt"
  })
}

resource "aws_route_table_association" "route_table_association" {
  for_each = local.subnet_map

  subnet_id      = aws_subnet.subnets[each.key].id
  route_table_id = aws_route_table.route_table.id
}