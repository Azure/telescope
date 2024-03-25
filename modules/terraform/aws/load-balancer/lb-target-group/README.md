# AWS Load Balancer Target Group Module

This module provisions a target group for an AWS load balancer. It allows you to create and configure a target group with customizable settings.

## Input Variables

### `run_id`

- **Description:** The run ID for the load balancer.
- **Type:** String

### `tags`

- **Description:** Tags to apply to the load balancer target group resources.
- **Type:** Map of strings
- **Default:** None

### `load_balancer_arn`

- **Description:** Value of the load balancer ARN.
- **Type:** String

### `lb_tg_config`

- **Description:** Configuration for the load balancer target group.
- **Type:** Object
  - `role`: Role of the load balancer target group
  - `tg_suffix`: Suffix for the target group
  - `port`: Port for the load balancer target group
  - `protocol`: Protocol for the load balancer target group
  - `rule_count`: Number of rules for the load balancer target group
  - `vpc_name`: Name of the VPC
  - `health_check`: Health check configuration for the load balancer target group
    - `port`: Port for health check
    - `protocol`: Protocol for health check
    - `interval`: Interval for health check
    - `timeout`: Timeout for health check
    - `healthy_threshold`: Healthy threshold for health check
    - `unhealthy_threshold`: Unhealthy threshold for health check
  - `lb_listener`: Listener configuration for the load balancer target group
    - `port`: Port for the listener
    - `protocol`: Protocol for the listener
  - `lb_target_group_attachment`: Attachment configuration for the load balancer target group
    - `vm_name`: Name of the virtual machine
    - `port`: Port for the attachment

## Usage Example

```hcl
module "load_balancer_target_group" {
  source = "./load-balancer-target-group-module"

  run_id            = "12345"
  load_balancer_arn = "arn:aws:elasticloadbalancing:us-west-2:123456789012:loadbalancer/app/my-load-balancer/1234567890abcdef"
  
  tags = {
    environment = "production"
    project     = "example"
  }

  lb_tg_config = {
    role       = "web"
    tg_suffix  = "tg"
    port       = 80
    protocol   = "HTTP"
    rule_count = 1
    vpc_name   = "my-vpc"
    health_check = {
      port                = 80
      protocol            = "HTTP"
      interval            = 30
      timeout             = 5
      healthy_threshold   = 2
      unhealthy_threshold = 2
    }
    lb_listener = {
      port     = 80
      protocol = "HTTP"
    }
    lb_target_group_attachment = {
      vm_name = "web-server"
      port    = 80
    }
  }
}
```

## Terraform Provider References

### Resources

- [aws_lb_target_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_target_group)
- [aws_lb_listener Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_listener)
- [aws_lb_target_group_attachment Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_target_group_attachment)

### Data Sources

- [aws_vpc Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc)
- [aws_instance Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/instance)
