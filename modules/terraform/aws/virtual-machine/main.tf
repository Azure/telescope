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
    name   = "tag:Name"
    values = ["${var.vm_config.security_group_name}"]
  }
}

data "aws_subnet" "subnet" {
  filter {
    name   = "tag:run_id"
    values = ["${var.run_id}"]
  }

  filter {
    name   = "tag:Name"
    values = ["${var.vm_config.subnet_name}"]
  }
}

resource "aws_instance" "vm" {
  ami               = data.aws_ami.ubuntu.id
  instance_type     = var.machine_type
  availability_zone = var.zone
  subnet_id         = data.aws_subnet.subnet.id

  vpc_security_group_ids = [data.aws_security_group.security_group.id]

  associate_public_ip_address = var.vm_config.associate_public_ip_address

  key_name = var.admin_key_pair_name

  user_data = file("${var.user_data_path}/${var.vm_config.role}-userdata.sh")

  tags = merge(var.tags, {
    "role" = "${var.vm_config.role}",
    "Name" = "${var.vm_config.vm_name}"
  })
}

resource "aws_ebs_volume" "data_disk" {
  count = var.vm_config.data_disk_config == null ? 0 : 1

  availability_zone = var.zone

  size       = var.vm_config.data_disk_config.data_disk_size_gb
  type       = var.vm_config.data_disk_config.data_disk_volume_type
  iops       = var.vm_config.data_disk_config.data_disk_iops_read_write
  throughput = var.vm_config.data_disk_config.data_disk_mbps_read_write
}

resource "aws_volume_attachment" "attach" {
  count = var.vm_config.data_disk_config == null ? 0 : 1

  device_name = "/dev/sdh"
  instance_id = aws_instance.vm.id
  volume_id   = aws_ebs_volume.data_disk[0].id
}
