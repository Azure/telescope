# AWS Virtual Machine Module

This module provisions a virtual machine (EC2 instance) in AWS with customizable configurations.

## Input Variables

### `vm_config`

- **Description:** Configuration for the virtual machine.
- **Type:** Object
  - `vm_name`: Name of the virtual machine
  - `role`: Role of the virtual machine
  - `subnet_name`: Name of the subnet
  - `security_group_name`: Name of the security group
  - `associate_public_ip_address`: Whether to associate a public IP address with the instance (boolean)
  - `zone_suffix`: Suffix for the availability zone
  - `data_disk_config`: (Optional) Configuration for the data disk
    - `data_disk_size_gb`: Size of the data disk in GB
    - `data_disk_volume_type`: Type of the data disk volume
    - `data_disk_iops_read_write`: (Optional) IOPS for read and write operations
    - `data_disk_mbps_read_write`: (Optional) Throughput for read and write operations
  - `ami_config`: (Optional) Configuration for the Amazon Machine Image (AMI)
    - `most_recent`: Whether to use the most recent AMI (boolean)
    - `name`: Name of the AMI
    - `virtualization_type`: Type of virtualization
    - `architecture`: Architecture of the AMI
    - `owners`: List of AMI owners

### `user_data_path`

- **Description:** Path to the user data script for configuring the instance.
- **Type:** String

### `machine_type`

- **Description:** Instance type for the virtual machine.
- **Type:** String
- **Default:** "m5.4xlarge"

### `run_id`

- **Description:** Value of the run ID.
- **Type:** String
- **Default:** "123456"

### `admin_key_pair_name`

- **Description:** Name of the admin key pair used to SSH into the instance.
- **Type:** String
- **Default:** "admin-key-pair"

### `tags`

- **Description:** Tags to apply to the virtual machine resources.
- **Type:** Map of strings
- **Default:** None

### `region`

- **Description:** AWS region where the virtual machine will be deployed.
- **Type:** String

## Example

```hcl
module "aws_virtual_machine" {
  source = "terraform-aws-modules/virtual-machine/aws"

  vm_config = {
    vm_name                     = "example-vm"
    role                        = "web-server"
    subnet_name                 = "example-subnet"
    security_group_name         = "example-security-group"
    associate_public_ip_address = true
    zone_suffix                 = "a"
    data_disk_config = {
      data_disk_size_gb         = 50
      data_disk_volume_type     = "gp2"
      data_disk_iops_read_write = 1000
      data_disk_mbps_read_write = 100
    }
    ami_config = {
      most_recent         = true
      name                = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
      virtualization_type = "hvm"
      architecture        = "x86_64"
      owners              = ["099720109477"]
    }
  }
  
  user_data_path      = "/path/to/user/data/script.sh"
  machine_type        = "t2.medium"
  run_id              = "123456789"
  admin_key_pair_name = "admin-key"
  tags = {
    environment = "production"
    project     = "example"
  }
  region = "us-west-2"
}
```

## Terraform Provider References

### Resources

- [aws_instance Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/instance)
- [aws_ebs_volume Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ebs_volume)
- [aws_volume_attachment Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/volume_attachment)

### Data Sources

- [aws_ami Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/ami)
- [aws_security_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/security_group)
- [aws_subnet Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet)
