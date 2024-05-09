# AWS Security Group Module

This module provisions a security group infrastructure in AWS, 

## Input Variables

### `network_config`

- **Description:** Configuration for the security group
- **Type:** Object
  - `sg_rules`: Security group rules configuration
    - `ingress`: List of ingress rules
    - `egress`: List of egress rules

### `region`

- **Description:** AWS region where the virtual network will be deployed.
- **Type:** String

### `tags`

- **Description:** Tags to apply to the virtual network resources.
- **Type:** Map of strings
- **Default:** None


## Example

```hcl
module "aws_virtual_network" {
  source = "terraform-aws-modules/virtual-network/aws"

  network_config = {
    vpc_name = "example-vpc"
    description = "sample security group"
    security_group_name = "example-security-group"
    sg_rules = {
      ingress = [
        {
          from_port = 22
          to_port = 22
          protocol = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
      egress = [
        {
          from_port = 0
          to_port = 0
          protocol = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  }
  
  region = "us-west-2"
  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [aws_vpc Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc)
- [aws_security_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group)


### Data Sources

- [aws_vpc Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc)
- [aws_security_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/security_group)
- [aws_subnet Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet)
