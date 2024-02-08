variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "cle-rg"
}

variable "location" {
  description = "Value of the location"
  type        = string
  default     = "East US"
}

variable "public_ip_config_list" {
  description = "Configuration for public Ip's."
  type = list(object({
    name              = string
    allocation_method = optional(string, "Static")
    sku               = optional(string, "Standard")
    zones             = optional(list(string), ["Zone-Redundant"])
  }))
}

variable "tags" {
  type = map(string)
  default = {
  }
}
