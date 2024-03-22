# AWS S3 Bucket Module

This module provisions an S3 bucket on AWS. It allows you to create and configure an S3 bucket with customizable settings.

## Input Variables

### `bucket_name_prefix`

- **Description:** Prefix for the bucket name.
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
