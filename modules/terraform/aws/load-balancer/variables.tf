variable "loadbalancer_config" {
  description = "Configuration for the load balancer."
  type = object({
    role                = string
    vpc_name            = string
    subnet_names        = list(string)
    load_balancer_type  = string
    security_group_name = optional(string)
    is_internal_lb      = optional(bool, false)
    lb_target_group = list(object({
      role      = string
      tg_suffix = string
      port      = number
      protocol  = string
      vpc_name  = string
      health_check = object({
        port                = number
        protocol            = string
        interval            = number
        timeout             = number
        healthy_threshold   = number
        unhealthy_threshold = number
      })
      lb_listener = list(object({
        port     = number
        protocol = string
      }))
      lb_target_group_attachment = list(object({
        vm_name = string
        port    = number
      }))
    }))
  })
}

variable "run_id" {
  description = "The run id for the load balancer."
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}
