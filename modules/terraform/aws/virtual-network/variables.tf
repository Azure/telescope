variable "network_config" {
  type = object({
    role            = string
    vpc_name               = string
    vpc_cidr_block         = string
    subnet_names           = list(string)
    subnet_cidr_block      = list(string)
    security_group_name    = string
    route_table_cidr_block = string
    sg_rules = object({
      ingress = list(object({
        from_port  = number
        to_port    = number
        protocol   = string
        cidr_block = string
      })),
      egress = list(object({
        from_port  = number
        to_port    = number
        protocol   = string
        cidr_block = string
      }))
    })
  })
}

variable "az" {
  description = "value of availability zone"
  type        = string
}

variable "job_id" {
  description = "Value of the job id"
  type        = string
  default     = ""
}

variable "tags" {
  type = map(string)
  default = {
  }
}
