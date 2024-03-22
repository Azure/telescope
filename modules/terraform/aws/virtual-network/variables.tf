variable "network_config" {
  type = object({
    role           = string
    vpc_name       = string
    vpc_cidr_block = string
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

variable "cross_region_peering" {
  description = "Flag to enable VNet peering between VNets in different regions"
  type        = bool
  default     = false
}

variable "run_id" {
  description = "Run ID of the current deployment"
  type = string
  default = ""
}