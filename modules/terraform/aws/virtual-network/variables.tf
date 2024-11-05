variable "network_config" {
  type = object({
    role                       = string
    vpc_name                   = string
    vpc_cidr_block             = string
    secondary_ipv4_cidr_blocks = optional(list(string))
    subnet = list(object({
      name                    = string
      cidr_block              = string
      zone_suffix             = string
      map_public_ip_on_launch = optional(bool, false)
    }))
    security_group_name = string
    route_tables = list(object({
      name             = string
      cidr_block       = string
      nat_gateway_name = optional(string)
    }))
    route_table_associations = list(object({
      name             = string
      subnet_name      = string
      route_table_name = string
    }))
    nat_gateway_public_ips = optional(list(object({
      name = string
    })))
    nat_gateways = optional(list(object({
      name           = string
      public_ip_name = string
      subnet_name    = string
    })))
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

