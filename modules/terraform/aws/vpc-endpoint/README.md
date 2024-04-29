# AWS VPC Endpoint module

This module provisions a vpc endpoint on AWS. It allows you to create and configure a vpc endpoint with customizable settings.

## Input Variables

### `vpc_id`

- **Description:** Id of vpc that the endpoint will be associated to
- **Type:** String
- **Default:** ""

### `pe_vpc_name`

- **Description:** Name of the created vpc endpoint
- **Type:** String
- **Default:** ""

### `region`

- **Description:** Region that the vpc endpoint will be deployed in
- **Type:** String
- **Default:** "us-east-2"

### `vpc_endpoint_type`

- **Description:** Region that the vpc endpoint will be deployed in
- **Type:** String
- **Default:** "us-east-2"

### `subnet_ids`

- **Description:** Subnet id's the vpc endpoint will be associated to
- **Type:** List(String)
- **Default:** []

### `security_group_ids`

- **Description:** Security group id's the vpc endpoint will be associated to
- **Type:** List(String)
- **Default:** []

### `route_table_ids`

- **Description:** Route table id's that the vpc endpoint will be associated to
- **Type:** List(String)
- **Default:** []

### `pe_config`

- **Description:** Configuration template for vpc endpoint configuration
- **Type:** Object(
    **pe_vpc_name:** String
    **service_name:** String
)
- **Default:** null

### `tags`

- **Description:** Tags to apply to the vpc endpoint.
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

### `vpc_endpoint`

- **Description:** Name of the created vpc endpoint.
- **Value:** The actual name of the vpc endpoint.

## Terraform Provider References

## Resources
- [aws_vpc_endpoint Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint)
