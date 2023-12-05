data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

data "aws_security_group" "security_group" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:role"
    values = ["${var.vm_config.network_role}"]
  }
}

data "aws_subnet" "subnet" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:role"
    values = ["${var.vm_config.network_role}"]
  }
}

resource "aws_instance" "vm" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.machine_type

  subnet_id = data.aws_subnet.subnet.id

  vpc_security_group_ids = [data.aws_security_group.security_group.id]

  associate_public_ip_address = var.vm_config.associate_public_ip_address

  key_name = var.admin_key_pair_name

  user_data = file("${var.user_data_path}/${var.vm_config.role}-userdata.sh")

  tags = merge(var.tags, {
    role = "${var.vm_config.role}"
  })
}
