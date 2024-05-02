# AWS VPC Endpoint module

This module provisions a vpc endpoint on AWS. It allows you to create and configure a vpc endpoint with customizable settings.

## Input Variables

### `vpc_id`

- **Description:** Id of vpc that the endpoint will be associated to
- **Type:** String
- **Default:** ""

### `pe_config`

- **Description:** Configuration template for vpc endpoint configuration
- **Type:** Object
    **pe_vpc_name:** String
    **pe_service_name:** String
    **vpc_endpoint_type:** String
    **subnet_ids:** Optional(List(string), [])
    **security_group_ids:** Optional(List(string), [])
    **route_table_ids:** Optional(List(string), [])
- **Default:** null

### `tags`

- **Description:** Tags to apply to the vpc endpoint.
- **Type:** Map of strings
- **Default:** None

## Usage Example

```hcl
module "privateendpoint" {
  source = "./vpc-endpoint"

  count     = var.pe_config == null ? 0 : 1
  pe_config = var.pe_config

  vpc_id = local.all_vpcs[var.pe_config.pe_vpc_name].id

  tags = local.tags
}
```

## Output Variables

### `vpc_endpoint`

- **Description:** Name of the created vpc endpoint.
- **Value:** The actual name of the vpc endpoint.

## Terraform Provider References

## Resources
- [aws_vpc_endpoint Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint)
