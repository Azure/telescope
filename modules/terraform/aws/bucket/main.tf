resource "aws_s3_bucket" "bucket" {
  bucket        = "${var.bucket_name_prefix}-${var.run_id}"
  tags          = var.tags
  force_destroy = true
}

resource "aws_s3_object" "object" {
  count  = var.object_config == null ? 0 : 1
  bucket = aws_s3_bucket.bucket.bucket
  key    = var.object_config.file_key
  source = var.object_config.source_path
  depends_on = [
    aws_s3_bucket.bucket
  ]
  tags = var.tags
}