variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "dns_zones" {
  description = "List of DNS zones to create"
  type = list(object({
    name = string
  }))
  default = []
}

variable "tags" {
  description = "Tags to apply to the DNS zones"
  type        = map(string)
  default     = {}
}