variable "vpc_id" {
    type = string
    default = ""
}

variable "region" {
    type = string
    default = "us-east-2"
}

variable "vpc_endpoint_type" {
    type = string
    default = "Gateway"
}

variable "subnet_ids" {
    type = list(string)
    default = []
}

variable "security_group_ids" {
    type = list(string)
    default = []
}

variable "route_table_ids" {
    type = list(string)
    default = []
}

variable "tags" {
  type = map(string)
  default = {
  }
}
