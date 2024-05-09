variable "sg_rules" {
  type = object({
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
}

variable "vpc_id" {
  description = "vpc to connect the security group to"
  type        = string
}

variable "description" {
  type = string
}

variable "security_group_name" {
  type = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}
