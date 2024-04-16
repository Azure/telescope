output "bucket_name" {
  value = aws_s3_bucket.bucket.bucket
}

output "bucket_object" {
  value = aws_s3_bucket_object.object
}