variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
}

variable "location" {
  description = "Value of the location"
  type        = string
}

variable "public_ip_config_list" {
  description = "Configuration for public Ip's."
  type = list(object({
    name              = string
    count             = optional(number, 1)
    allocation_method = optional(string, "Static")
    sku               = optional(string, "Standard")
    zones             = optional(list(string), [])
  }))
}

variable "tags" {
  type = map(string)
}

variable "pip_count_override" {
  description = "value the number of modules to create, overrides tfvars definition if greater than 0"
  type        = number
  default     = 0
}
