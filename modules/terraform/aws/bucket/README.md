# AWS S3 Bucket Module

This module provisions an S3 bucket on AWS. It allows you to create and configure an S3 bucket with customizable settings.

## Input Variables

### `bucket_name_prefix`

- **Description:** Prefix for the bucket name.
- **Type:** String
- **Default:** ""

### `bucket_file_key`

- **Description:** Desired name for bucket file.
- **Type:** String
- **Default:** ""

### `bucket_file_path`

- **Description:** Local path for file to be uploaded to bucket.
- **Type:** String
- **Default:** ""

### `run_id`

- **Description:** Run ID for the bucket.
- **Type:** String
- **Default:** ""

### `tags`

- **Description:** Tags to apply to the S3 bucket resources.
- **Type:** Map of strings
- **Default:** None

## Usage Example

```hcl
module "s3_bucket" {
  source = "./s3-bucket"

  bucket_file_key    = "test"
  bucket_file_path   = "${localPath}/testfile.test"
  bucket_name_prefix = "example-bucket"
  run_id             = "12345"
  
  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Output Variables

### `bucket_name`

- **Description:** Name of the created S3 bucket.
- **Value:** The actual name of the S3 bucket created.

### `bucket_object`

- **Description:** Name of the created S3 bucket object.
- **Value:** The actual name of the S3 bucket object created.

## Terraform Provider References

## Resources
- [aws_s3_bucket Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket)
