data "aws_ami" "ubuntu" {
  most_recent = var.vm_config.ami_config.most_recent

  filter {
    name   = "name"
    values = [var.vm_config.ami_config.name]
  }

  filter {
    name   = "virtualization-type"
    values = [var.vm_config.ami_config.virtualization_type]
  }

  filter {
    name   = "architecture"
    values = [var.vm_config.ami_config.architecture]
  }

  owners = var.vm_config.ami_config.owners
}

data "aws_security_group" "security_group" {
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [var.vm_config.security_group_name]
  }
}

data "aws_subnet" "subnet" {
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [var.vm_config.subnet_name]
  }
}

resource "aws_instance" "vm" {
  ami               = data.aws_ami.ubuntu.id
  instance_type     = var.machine_type
  availability_zone = "${var.region}${var.vm_config.zone_suffix}"
  subnet_id         = data.aws_subnet.subnet.id

  vpc_security_group_ids = [data.aws_security_group.security_group.id]

  associate_public_ip_address = var.vm_config.associate_public_ip_address

  key_name = var.admin_key_pair_name

  user_data = file("${var.user_data_path}/${var.vm_config.role}-userdata.sh")

  placement_group = var.vm_config.placement_group == false ? null : var.run_id

  tags = merge(var.tags, {
    "role"             = var.vm_config.role,
    "Name"             = var.vm_config.vm_name,
    "info_column_name" = var.vm_config.info_column_name
  })
}
