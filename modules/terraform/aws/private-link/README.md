# AWS Private Link Module

This module provisions an AWS Private Link connection between a service and a client using a load balancer.

## Input Variables

### `run_id`

- **Description:** The run ID for the Private Link.
- **Type:** String

### `tags`

- **Description:** Tags to apply to the Private Link resources.
- **Type:** Map of strings
- **Default:** None

### `service_lb_arn`

- **Description:** The ARN of the load balancer for the service.
- **Type:** String

### `client_vpc_name`

- **Description:** The name of the VPC for the client.
- **Type:** String

### `client_subnet_name`

- **Description:** The name of the subnet for the client.
- **Type:** String

### `client_security_group_name`

- **Description:** The name of the security group for the client.
- **Type:** String

## Example

```hcl
module "aws_private_link" {
  source = "terraform-aws-modules/private-link/aws"

  run_id                     = "12345"
  service_lb_arn             = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-load-balancer/1234567890abcdef"
  client_vpc_name            = "client-vpc"
  client_subnet_name         = "client-subnet"
  client_security_group_name = "client-security-group"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```