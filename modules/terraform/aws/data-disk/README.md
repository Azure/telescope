# Data Disk Module

This module provisions data disks in Aws. It allows you to create and configure data disks with customizable settings.

## Input Variables

### `data_disk_volume_type`

- **Description:** Volume type for the data disks.
- **Type:** String
- **Default:** ""

### `data_disk_size_gb`

- **Description:** Size of the data disks in gigabytes.
- **Type:** String
- **Default:** ""

### `data_disk_iops_read_write`

- **Description:** IOPS (Input/Output Operations Per Second) for read and write operations.
- **Type:** Number
- **Default:** null

### `data_disk_mbps_read_write`

- **Description:** Throughput limit in MBps (Megabytes Per Second) for read and write operations.
- **Type:** Number
- **Default:** null

### `tags`

- **Type:** Map of strings
- **Default:** None

### `zone`

- **Description:** Availability zone for the data disks.
- **Type:** String
- **Default:** None

## Usage Example

```hcl
module "data_disk" {
  source = "./data-disk"

  data_disk_volume_type          = "gp2"
  data_disk_size_gb              = "128"
  zone                           = "us-east-2a"
  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [aws_ebs_volume Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ebs_volume)
