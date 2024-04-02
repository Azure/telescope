# AWS Virtual Network Module

This module provisions a virtual network infrastructure in AWS, including a VPC, subnets, security groups, route tables, and associated resources.

## Input Variables

### `network_config`

- **Description:** Configuration for the virtual network.
- **Type:** Object
  - `role`: Role of the virtual network
  - `vpc_name`: Name of the VPC
  - `vpc_cidr_block`: CIDR block for the VPC
  - `subnet`: List of subnet configurations
    - `name`: Name of the subnet
    - `cidr_block`: CIDR block for the subnet
    - `zone_suffix`: Suffix for the availability zone
    - `map_public_ip_on_launch`: Whether to map public IP on instance launch (boolean)
  - `security_group_name`: Name of the security group
  - `route_tables`: List of route table configurations
    - `name`: Name of the route table
    - `cidr_block`: CIDR block for the route table
    - `nat_gateway_name`: (Optional) Name of the NAT gateway associated with the route table
  - `route_table_associations`: List of route table associations
    - `name`: Name of the route table association
    - `subnet_name`: Name of the associated subnet
    - `route_table_name`: Name of the associated route table
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
    role = "example-network"
    vpc_name = "example-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name = "example-subnet"
        cidr_block = "10.0.1.0/24"
        zone_suffix = "a"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "example-security-group"
    route_tables = [
      {
        name = "example-route-table"
        cidr_block = "0.0.0.0/0"
        nat_gateway_name = "example-nat-gateway"
      }
    ]
    route_table_associations = [
      {
        name = "example-route-table-association"
        subnet_name = "example-subnet"
        route_table_name = "example-route-table"
      }
    ]
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
- [aws_subnet Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet)
- [aws_eip Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eip)
- [aws_nat_gateway Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/nat_gateway)
- [aws_security_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group)
- [aws_internet_gateway Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/internet_gateway)
- [aws_route_table Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table)
- [aws_route_table_association Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association)

### Data Sources

- [aws_vpc Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc)
- [aws_security_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/security_group)
- [aws_subnet Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet)
