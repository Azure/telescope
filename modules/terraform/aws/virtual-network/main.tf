locals {
  role                 = var.network_config.role
  ingress_sg_rules_map = { for idx, rule in var.network_config.sg_rules.ingress : idx => rule }
  egress_sg_rules_map  = { for idx, rule in var.network_config.sg_rules.egress : idx => rule }
  vpc_name             = var.network_config.vpc_name
  subnet_names         = var.network_config.subnet_names
  subnet_cidr_blocks   = var.network_config.subnet_cidr_block
  security_group_name  = var.network_config.security_group_name
}


resource "aws_vpc" "vpc" {
  cidr_block = var.network_config.vpc_cidr_block

  tags = merge(var.tags, {
    Name = "${local.vpc_name}-${var.job_id}"
  })
}

resource "aws_subnet" "subnets" {
  count = length(local.subnet_names)

  vpc_id     = aws_vpc.vpc.id
  cidr_block = local.subnet_cidr_blocks[count.index]

  availability_zone = var.az

  tags = merge(var.tags, {
    Name = "${local.subnet_names[count.index]}-${var.job_id}"
  })
}


resource "aws_security_group" "security_group" {
  name = "${local.security_group_name}-${var.job_id}"

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

  tags = var.tags
}

resource "aws_internet_gateway" "internet_gateway" {
  vpc_id = aws_vpc.vpc.id

  tags = merge(var.tags, {
    Name = "${local.role}-igw-${var.job_id}"
  })
}

resource "aws_route_table" "route_table" {
  vpc_id = aws_vpc.vpc.id

  route {
    cidr_block = var.network_config.route_table_cidr_block
    gateway_id = aws_internet_gateway.internet_gateway.id
  }

  tags = merge(var.tags, {
    Name = "${local.role}-rtb-${var.job_id}"
  })
}

resource "aws_route_table_association" "route_table_association" {
  count = length(local.subnet_names)

  subnet_id      = aws_subnet.subnets[count.index].id
  route_table_id = aws_route_table.route_table.id
}
