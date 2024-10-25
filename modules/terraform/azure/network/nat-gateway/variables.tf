variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "nat_gateway_name" {
  description = "Value of the nat gateway name"
  type        = string
}

variable "subnet_id" {
  description = "Value of the subnet id"
  type        = string
}

variable "public_ip_address_id" {
  description = "Value of the public ip address id"
  type        = string
}

variable "tags" {
  type = map(string)
}
