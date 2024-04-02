# AWS Elastic File System (EFS) Module

This module provisions an Elastic File System (EFS) on AWS. It allows you to create and configure an EFS with customizable settings.

## Input Variables

### `efs_name_prefix`

- **Description:** Prefix for the EFS name.
- **Type:** String
- **Default:** ""

### `run_id`

- **Description:** Run ID for the EFS.
- **Type:** String
- **Default:** ""

### `performance_mode`

- **Description:** The file system performance mode. Can be either 'generalPurpose' or 'maxIO'.
- **Type:** String
- **Default:** "generalPurpose"

### `throughput_mode`

- **Description:** Throughput mode for the file system. Can be 'bursting', 'provisioned', or 'elastic'. Defaults to 'bursting'.
- **Type:** String
- **Default:** "bursting"

### `provisioned_throughput_in_mibps`

- **Description:** The throughput, measured in MiB/s, that you want to provision for the file system. Only applicable with `throughput_mode` set to 'provisioned'.
- **Type:** Number
- **Default:** null

### `tags`

- **Description:** Tags to apply to the EFS resources.
- **Type:** Map of strings
- **Default:** {}

## Usage Example

```hcl
module "efs" {
  source = "./efs"

  efs_name_prefix               = "example-efs"
  run_id                        = "12345"
  performance_mode              = "generalPurpose"
  throughput_mode               = "bursting"
  provisioned_throughput_in_mibps = null
  
  tags = {
    environment = "production"
    project     = "example"
  }
}
```
## Output Variables

### `efs_creation_token`

- **Description:** Creation token of the created Elastic File System (EFS).
- **Value:** The creation token of the EFS.

## Terraform Provider References

## Resources

- [aws_efs_file_system Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_file_system)