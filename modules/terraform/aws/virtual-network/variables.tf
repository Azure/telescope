variable "network_config" {
  type = object({
    role           = string
    vpc_name       = string
    vpc_cidr_block = string
    subnet = list(object({
      name        = string
      cidr_block  = string
      zone_suffix = string
    }))
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

variable "region" {
  description = "value of region"
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
  }
}
