# AWS Load Balancer Module

This module provisions an AWS load balancer and associated target groups. It provides flexibility in configuring various aspects of the load balancer and target groups.

## Input Variables

### `loadbalancer_config`

- **Description:** Configuration for the load balancer.
- **Type:** Object
  - `role`: The role of the load balancer.
  - `subnet_name`: The name of the subnet for the load balancer.
  - `load_balancer_type`: The type of the load balancer. Could be application 
  - `security_group_name`: Security Group name. Needed for Application load balancers. 
  - `is_internal_lb`: (Optional) Specifies if the load balancer is internal or not. Defaults to `false`.
  - `lb_target_group`: A list of objects representing target group configurations.
    - `role`: The role of the target group.
    - `tg_suffix`: The suffix for the target group.
    - `port`: The port for the target group.
    - `protocol`: The protocol for the target group.
    - `rule_count`: The number of rules for the target group.
    - `vpc_name`: The name of the VPC for the target group.
    - `health_check`: An object representing health check configuration.
      - `port`: The port for health check.
      - `protocol`: The protocol for health check.
      - `interval`: The interval for health check.
      - `timeout`: The timeout for health check.
      - `healthy_threshold`: The healthy threshold for health check.
      - `unhealthy_threshold`: The unhealthy threshold for health check.
    - `lb_listener`: An object representing listener configuration.
      - `port`: The port for the listener.
      - `protocol`: The protocol for the listener.
    - `lb_target_group_attachment`: An object representing target group attachment configuration.
      - `vm_name`: The name of the VM.
      - `port`: The port for the target group attachment.

### `run_id`

- **Description:** The run ID for the load balancer.
- **Type:** String

### `tags`

- **Description:** Tags to apply to the load balancer resources.
- **Type:** Map of strings
- **Default:** None

## Example

```hcl
module "aws_lb" {
  source = "terraform-aws-modules/alb/aws"

  loadbalancer_config = {
    role               = "web"
    subnet_name        = "public-subnet"
    load_balancer_type = "application"
    is_internal_lb     = false
    lb_target_group = [
      {
        role       = "web"
        tg_suffix  = "web-tg"
        port       = 80
        protocol   = "HTTP"
        rule_count = 2
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
    ]
  }

  run_id = "12345"

  tags = {
    environment = "production"
    project     = "example"
  }
}
```

## Terraform Provider References

### Resources

- [aws_lb Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb)

### Data Sources

- [aws_subnet Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet)
