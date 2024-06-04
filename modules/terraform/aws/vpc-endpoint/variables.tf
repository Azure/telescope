variable "vpc_id" {
  type    = string
  default = ""
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

variable "tags" {
  type = map(string)
  default = {
  }
}