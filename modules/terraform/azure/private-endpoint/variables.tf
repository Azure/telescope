variable "location" {
  description = "Location of private endpoint"
  type        = string
  default     = "East US"
}


variable "resource_group_name" {
  description = "Value of the resource group name"
  type        = string
  default     = "rg"
}


variable "pe_subnet_id" {
  description = "ID of the private endpoint's subnet"
  type        = string
  default     = ""
}

variable "private_connection_resource_id" {
  description = "ID of the private service connection's resource"
  type        = string
  default     = ""
}

variable "pe_config" {
  description = "configuration for a private endpoint"
  type = object({
    pe_name              = string
    pe_subnet_name       = string
    psc_name             = string
    is_manual_connection = optional(bool, false)
    subresource_names    = optional(list(string))
  })
  default = null
}

variable "tags" {
  type = map(string)
  default = {
  }
}