
variable "run_id" {
  description = "The run id for the load balancer."
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}

variable "service_lb_arn" {
  description = "The arn of the load balancer."
  type        = string
}

variable "client_vpc_name" {
  description = "The vpc name for client."
  type        = string
}

variable "client_subnet_name" {
  description = "The subnet name for client."
  type        = string
}

variable "client_security_group_name" {
  description = "The security group name for client."
  type        = string
}