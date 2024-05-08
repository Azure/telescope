
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

variable "pe_config" {
  description = "configuration for vpc private endpoint"
  type = object({
    pe_vpc_name        = string
    pe_service_name    = string
    vpc_endpoint_type  = string
    subnet_ids         = optional(list(string), [])
    security_group_ids = optional(list(string), [])
    route_table_ids    = optional(list(string), [])
  })
  default = null
}