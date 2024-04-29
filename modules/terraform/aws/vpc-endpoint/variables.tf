variable "vpc_id" {
  type    = string
  default = ""
}

variable "pe_vpc_name" {
  type    = string
  default = "same-vpc"
}

variable "region" {
  type    = string
  default = "us-east-2"
}

variable "vpc_endpoint_type" {
  type    = string
  default = "Gateway"
}

variable "subnet_ids" {
  type    = list(string)
  default = []
}

variable "security_group_ids" {
  type    = list(string)
  default = []
}

variable "route_table_ids" {
  type    = list(string)
  default = []
}

variable "pe_config" {
  description = "configuration for vpc private endpoint"
  type = object({
    pe_vpc_name = string
    service_name = string
  })
}

variable "tags" {
  type = map(string)
  default = {
  }
}