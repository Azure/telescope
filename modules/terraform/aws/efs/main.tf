resource "aws_efs_file_system" "efs" {
  creation_token                  = "${var.efs_name_prefix}-${var.run_id}"
  performance_mode                = var.performance_mode
  throughput_mode                 = var.throughput_mode
  provisioned_throughput_in_mibps = var.provisioned_throughput_in_mibps

  tags = var.tags
}

