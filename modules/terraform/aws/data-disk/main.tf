resource "aws_ebs_volume" "data_disk" {
  availability_zone = var.zone

  size       = var.data_disk_size_gb
  type       = var.data_disk_volume_type
  iops       = var.data_disk_iops_read_write
  throughput = var.data_disk_mbps_read_write

  tags = var.tags
}
