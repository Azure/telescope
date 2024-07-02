variable "run_id" {
  description = "The run id for the load balancer."
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "load_balancer_arn" {
  description = "value of the load balancer arn"
  type        = string
}

variable "lb_tg_config" {
  description = "Configuration for the load balancer target group."
  type = object({
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
  })
}
