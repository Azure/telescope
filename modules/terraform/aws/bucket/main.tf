resource "aws_s3_bucket" "bucket" {
  bucket        = "${var.bucket_name_prefix}-${var.run_id}"
  source        = var.bucket_source_path
  tags          = var.tags
  force_destroy = true
}