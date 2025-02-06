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

variable "public_ips" {
  description = "Map of public IP names to IDs"
  type        = map(string)
}

variable "tags" {
  type = map(string)
}

variable "nat_gateway_association" {
  description = "NAT Gateway association"
  type = object({
    nat_gateway_name = string
    public_ip_names  = list(string)
    subnet_names     = list(string)
  })
}

variable "subnets_map" {
  description = "Map of subnets"
  type        = map(any)
}
