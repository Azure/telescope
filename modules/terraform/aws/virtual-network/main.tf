locals {
  ingress_sg_rules_map         = var.network_config.sg_rules == null ? {} : { for idx, rule in var.network_config.sg_rules.ingress : idx => rule }
  egress_sg_rules_map          = var.network_config.sg_rules == null ? {} : { for idx, rule in var.network_config.sg_rules.egress : idx => rule }
  vpc_name                     = var.network_config.vpc_name
  subnet_map                   = { for subnet in var.network_config.subnet : subnet.name => subnet }
  route_tables_map             = var.network_config.route_tables == null ? {} : { for rt in var.network_config.route_tables : rt.name => rt }
  route_table_associations_map = var.network_config.route_table_associations == null ? {} : { for rta in var.network_config.route_table_associations : rta.name => rta }
  nat_gateway_public_ips_map   = var.network_config.nat_gateway_public_ips == null ? {} : { for pip in var.network_config.nat_gateway_public_ips : pip.name => pip }
  nat_gateways_map             = var.network_config.nat_gateways == null ? {} : { for ng in var.network_config.nat_gateways : ng.name => ng }

  security_group_name = var.network_config.security_group_name
  tags                = merge(var.tags, { "role" = var.network_config.role })
}

resource "aws_vpc" "vpc" {
  cidr_block = var.network_config.vpc_cidr_block

  tags = merge(local.tags, {
    "Name" = local.vpc_name
  })
}

resource "aws_subnet" "subnets" {
  for_each = local.subnet_map

  vpc_id                  = aws_vpc.vpc.id
  cidr_block              = each.value.cidr_block
  map_public_ip_on_launch = each.value.map_public_ip_on_launch

  availability_zone = "${var.region}${each.value.zone_suffix}"

  tags = merge(local.tags, {
    "Name" = each.value.name
  })

  provisioner "local-exec" {
    /*
      This command cleans up any not in use ENIs attached to this subnet, which were created outside the scope of the Terraform modules.
      This is a workaround for the known VPC CNI addon's "leaked ENIs" issue: See https://github.com/aws/amazon-vpc-cni-k8s/issues/608
    */
    when    = destroy
    command = <<-EOT
      echo "Detaching Subnet: ${self.id} Network Interfaces"
      # Get available (not in use) ENIs attached to this subnet
      network_interfaces_attachment_ids=$(aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=${self.id} --query "NetworkInterfaces[?Status=='available' && Attachment.AttachIndex != '0'].Attachment.AttachmentId" --output text)
      for network_interface_attachment_id in $network_interfaces_attachment_ids; do
        echo "Detaching available Network Interface attachment id: $network_interface_attachment_id"
        if ! aws ec2 detach-network-interface --attachment-id $network_interface_attachment_id; then
          echo "##[warning] Failed to detach Network Interface attachment id: $network_interface_attachment_id"
        fi
      done
      network_interfaces=$(aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=${self.id} --query "NetworkInterfaces[?Status=='available' && Attachment.AttachIndex != '0'].NetworkInterfaceId" --output text)
      for network_interface in $network_interfaces; do
        echo "Deleting available Network Interface: $network_interface"
        if ! aws ec2 delete-network-interface --network-interface-id $network_interface; then
          echo "##[warning] Failed to delete Network Interface: $network_interface"
        fi
      done
    EOT
  }
}

resource "aws_eip" "eips" {
  for_each = local.nat_gateway_public_ips_map

  domain = "vpc"

  tags = merge(local.tags, {
    "Name" = each.value.name
  })
}

resource "aws_nat_gateway" "nat-gateways" {
  for_each = local.nat_gateways_map

  allocation_id = aws_eip.eips[each.value.public_ip_name].id
  subnet_id     = aws_subnet.subnets[each.value.subnet_name].id

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

resource "aws_route_table" "route_tables" {
  for_each = local.route_tables_map

  vpc_id = aws_vpc.vpc.id

  route {
    cidr_block = each.value.cidr_block
    gateway_id = each.value.nat_gateway_name == null ? aws_internet_gateway.internet_gateway.id : aws_nat_gateway.nat-gateways[each.value.nat_gateway_name].id
  }

  tags = merge(local.tags, {
    "Name" = each.value.name
  })
}

resource "aws_route_table_association" "route_table_association" {
  for_each = local.route_table_associations_map

  subnet_id      = aws_subnet.subnets[each.value.subnet_name].id
  route_table_id = aws_route_table.route_tables[each.value.route_table_name].id
}
